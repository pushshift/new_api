#!/usr/bin/env python3

import falcon
import yaml
import redis,hiredis
import time
import math
import dataviz
import ujson as json
import requests
import parameters
import elasticsearch
import aggregations
import hashlib
from collections import defaultdict
from collections import OrderedDict
import urllib

API_VERSION = "4.0"

class MiddleWare:

    def __init__(self):
        self.param_info = yaml.load(open("valid_params.yaml"))
        self.valid_params = set(self.param_info.keys())
        #self.r = redis.StrictRedis(host='localhost', port=6379, db=0)
        self.daily_limit = 1000
        self.visualization_params = set()
        for key in self.param_info.keys():
            if 'category' in self.param_info[key] and self.param_info[key]['category'] == 'visualization':
                self.visualization_params.add(key)

    def process_request(self, req, resp):

        req.context['visualization_params'] = self.visualization_params

        # Reorder parameters sorted alphabetically for caching purposes
        encoded_ordered_params = urllib.parse.urlencode(sorted(req.params.items()))
        self.ordered_url = "{}?{}".format(req.path,encoded_ordered_params).rstrip('?').encode('utf-8')
        req.context['url_hash'] = hashlib.sha256(self.ordered_url).hexdigest()


        if req.params.get('output') in ['png']:
            ordered_params_without_viz = req.params.copy()
            for key in req.context['visualization_params']:
                ordered_params_without_viz.pop(key,None)
            encoded_ordered_params_without_viz = urllib.parse.urlencode(sorted(ordered_params_without_viz.items()))
            self.ordered_url_without_viz = "{}?{}".format(req.path,encoded_ordered_params_without_viz).rstrip('?').encode('utf-8')
            req.context['url_hash_without_viz'] = hashlib.sha256(self.ordered_url_without_viz).hexdigest()

            # Check if exact request exists in cache
            data,image_data = api.r.mget('data-{}'.format(req.context['url_hash']),req.context['url_hash'])
            if data is not None and image_data is not None:
                req.context['image_data'] = image_data
                req.context['data'] = data
                req.context['reprocess'] = False
                req.path = "/cache"
            else:
                # Check if request with same data parameters but different viz parameters exist
                data = api.r.get('data-{}'.format(req.context['url_hash_without_viz']))
                if data is not None:
                    req.context['data'] = data
                    req.context['reprocess'] = True
                    req.path = "/cache"

        # Get API key if it exists
        self.api_key = req.get_header('api-key')

        # Get Requester's IP Address
        if 'HTTP_CF_CONNECTING_IP' in req.env:
            self.ip_address = req.env['HTTP_CF_CONNECTING_IP']
        else:
            self.ip_address = "unknown"

        # req.context and resp.context (dicts) can be used to stash data
        req.context["start_time"] = time.time()

        # Get type of request (comment,submission,etc.)
        path = req.path.lower()
        req.context['type'] = None
        if 'comment' in path:
            req.context['type'] = 'comment'
        elif 'submission' in path:
            req.context['type'] = 'submission'
        elif 'subreddit' in path:
            req.context['type'] = 'subreddit'

    def process_resource(self, req, resp, resource, params):

        # Make copy of original parameters
        self.original_parameters = req.params.copy()

        # Remap deprecated keys
        for key in req.params.keys():
            if key in self.param_info and 'alias to' in self.param_info[key]:
                req.params[self.param_info[key]['alias to']] = req.params[key]
                req.params.pop(key,None)

        # Sanity Check for request -- make sure there are no unknown parameters and that present parameters have correct types
        for key in req.params.keys():
            #if isinstance(req.params[key],str):
            #    req.params[key] = req.params[key].lower()  # Lowercase all parameter values

            if key not in self.valid_params:
                raise falcon.HTTPInvalidParam(  'Please remember to keep all parameters lowercase.',key,
                                                href='https://api.pushshift.io/valid_parameters',
                                                href_text='Refer to this link for a list of valid parameters')

            # Check all parameter values for type compliance
            valid_type = self.param_info[key]['type']

            if valid_type == 'numeric':
                try:
                    req.params[key] = int(req.params[key])
                except:
                    raise falcon.HTTPUnprocessableEntity(description="The {} parameter should be numeric (only contain numbers)".format(key))
                if 'max size' in self.param_info[key] and req.params[key] > self.param_info[key]['max size']:
                    raise falcon.HTTPUnprocessableEntity(description="The {} parameter is too large.  The max value for this parameter is {}.".format(key,self.param_info[key]['max size']))
                if 'min size' in self.param_info[key] and req.params[key] < self.param_info[key]['min size']:
                    raise falcon.HTTPUnprocessableEntity(description="The {} parameter cannot be less than {}.".format(key,self.param_info[key]['min size']))

            if valid_type == 'boolean':
                if req.params[key] not in ['true','false']:
                    raise falcon.HTTPUnprocessableEntity(description="The {} parameter is a boolean and should be set to true or false.".format(key))
                else:
                    req.params[key] = True if req.params[key] == 'true' else False

        num_of_calls = api.r.get(self.ip_address)
        if num_of_calls is not None:
            num_of_calls = int(num_of_calls)
        else:
            num_of_calls = 0
        expire_in = math.ceil(time.time()/86400)*86400 - int(time.time())
        x_ratelimit_remaining = self.daily_limit - num_of_calls
        if x_ratelimit_remaining < 0: x_ratelimit_remaining = 0
        resp.append_header('X-RateLimit-Remaining',x_ratelimit_remaining-1)

        if not x_ratelimit_remaining:
            raise falcon.HTTPTooManyRequests(   title="Requests Exhausted",
                                                description="You have used the daily allotment of free requests.  The free daily allotment will reset in " + "{:,}".format(expire_in) + " seconds.")
        # Update rate-limit info in Redis
        p = api.r.pipeline()
        if expire_in != 0 and expire_in < 86399:
            p.incr(self.ip_address, amount=1)
            p.expire(self.ip_address,expire_in)
        else:
            p.set(self.ip_address,0)
        p.execute()

        # Process Parameters
        parameters.Process(self,req)

    def process_response(self,req,resp,resource,req_succeeded):

        if req_succeeded and req.context['type'] in ['comment','submission'] and 'stop_post_processing' not in req.context:
            resp.cache_control = ['private','max-age=1']
            image_data = self.process_image(req)
            data = {}
            json_args = {}
            json_args['ensure_ascii'] = False

            # Check if ensure_ascii was requested
            if 'ensure_ascii' in req.params and req.params['ensure_ascii']:
                json_args['ensure_ascii'] = True

            # Check if pretty print was requested
            if 'pretty' in req.params and req.params['pretty']:
                json_args['indent'] = 4

            # Check if data exists
            if 'data' in req.context:
                data['data'] = req.context['data']

            # Check if aggregations exist
            if 'aggs' in req.context:
                data['aggs'] = req.context['aggs']

            # Check if metadata was requested
            if 'metadata' in req.context:
                data['metadata'] = req.context['metadata']
                data['metadata']['original_params'] = self.original_parameters
                data['metadata']['interpreted_params'] = req.params
                data['metadata']['type'] = req.context['type']

            json_data = json.dumps(data,**json_args)
            json_cache_data = json.dumps(data)  # No pretty
            api.r.set('data-{}'.format(req.context['url_hash']),json_cache_data,300)

            if 'url_hash_without_viz' in req.context:
                api.r.set('data-{}'.format(req.context['url_hash_without_viz']),json_cache_data,300)

            if 'metadata' not in req.params or ('metadata' in req.params and req.params['metadata'] == False):
                data.pop('metadata',None)
                json_data = json.dumps(data,**json_args)

            if image_data:
                api.r.set(req.context['url_hash'],image_data,300)
                resp.append_header('content-type','image/png')
                resp.body = image_data
            else:
                resp.body = json_data

    def process_image(self,req):
        if 'output' in req.params and req.params['output'] == 'png':
            if 'aggregation' in req.params and req.params['aggregation'][0].startswith("created_utc"):
                image = dataviz.create_timeline(req,[])
            if 'aggregation' in req.params and ('subreddit' in req.params['aggregation'] or 'author' in req.params['aggregation']):
                image = dataviz.create_chart(req,[])
            image_data = image.read()
            return image_data

class fetch_cache:
    def on_get(self, req, resp):
        if 'data' not in req.context:
            resp.body = "I am the cache endpoint!"
        else:
            if req.context['reprocess']:
                j = json.loads(req.context['data'])
                original_params = j['metadata']['interpreted_params']
                for key in original_params.keys():
                    if key in req.context['visualization_params']: continue
                    req.params[key] = original_params[key]
                if 'metadata' in j:
                    req.context['type'] = j['metadata']['type']
                req.context['aggs'] = j['aggs']
                req.context['image_data'] = MiddleWare.process_image(None,req)
                api.r.set('data-{}'.format(req.context['url_hash']),req.context['data'],300)
                api.r.set(req.context['url_hash'],req.context['image_data'],300)
            req.context['stop_post_processing'] = True
            resp.cache_control = ['private','max-age=1']
            resp.append_header('content-type','image/png')
            resp.body = req.context['image_data']

def handle_404(req, resp):
    # Default sink for unknown paths
    resp.status = falcon.HTTP_404
    resp.cache_control = ['public','max-age=60','s-maxage=60']
    resp.media = {'error': 'Unknown path'}

class test_image:
    def on_get(self, req, resp):
        f = open('line.gif','rb')
        data = f.read()
        resp.append_header('content-type','image/gif')
        resp.body = data

class submission_search:
    def on_get(self, req, resp):

        nested_dict = lambda: defaultdict(nested_dict)

        if 'q' in req.params:
            sqs = nested_dict()
            sqs['simple_query_string']['query'] = req.params['q']
            sqs['simple_query_string']['fields'] = ["title^5","selftext^2"]
            sqs['simple_query_string']['default_operator'] = 'and'
            req.context['es_query']['query']['bool']['must'].append(sqs)

        conditions = ["title","selftext"]
        for condition in conditions:
            if condition in req.params:
                sqs = nested_dict()
                sqs['simple_query_string']['query'] = req.params[condition]
                sqs['simple_query_string']['fields'] = [condition]
                sqs['simple_query_string']['default_operator'] = 'and'
                req.context['es_query']['query']['bool']['must'].append(sqs)

        es_connector.query_es(req)

class comment_search:
    def on_get(self, req, resp):

        nested_dict = lambda: defaultdict(nested_dict)

        if 'q' in req.params:
            sqs = nested_dict()
            sqs['simple_query_string']['query'] = req.params['q']
            sqs['simple_query_string']['fields'] = ['body']
            sqs['simple_query_string']['default_operator'] = 'and'
            req.context['es_query']['query']['bool']['must'].append(sqs)

        data = self.doElasticSearch(req)
        resp.context['data'] = data

    def doElasticSearch(self,req):

        req.params['index'] = 'rc'
        response = self.search(req,"http://localhost:9200/" + req.params['index'] + "/comment/_search")

    def search(self,req,uri):

        es_connector.query_es(req)

# Not sure if this is the best place for this object -- need it to be long-lived so it isn't destroyed after every connection
es_connector = elasticsearch.Connector()
########################################

class App(falcon.API):
    def __init__(self, *args, **kwargs):
        super(App, self).__init__(*args, **kwargs)
        self.r = redis.StrictRedis(host='localhost', port=6379, db=0, decode_responses=True)

api = App(middleware=[MiddleWare()])
api.req_options.keep_blank_qs_values = True

#api.add_route('/reddit/subreddit/search', Subreddit.search())
#api.add_route('/reddit/search/subreddit', Subreddit.search())
api.add_route('/reddit/search', comment_search())
api.add_route('/reddit/comment/search', comment_search())
api.add_route('/reddit/search/comment', comment_search())
api.add_route('/reddit/search/submission', submission_search())
api.add_route('/reddit/submission/search', submission_search())
#api.add_route('/reddit/analyze/user/{author}', User.Analyze())
#api.add_route('/reddit/get/comment_ids/{submission_id}', Submission.getCommentIDs())
#api.add_route('/reddit/submission/comment_ids/{submission_id}', Submission.getCommentIDs())
#api.add_route('/reddit/submission/comment_ids/{submission_id}', Submission.getCommentIDs())
#api.add_route('/meta',Metadata.metadata())
#api.add_route('/reddit/statistics', Statistics.statistics())
#api.add_route('/reddit/submission/timeline/{submission_id}', Submission.timeLine())
api.add_route('/test_image',test_image())
api.add_route('/cache',fetch_cache())
api.add_sink(handle_404, '')

#api.add_route('/',Test.test())

