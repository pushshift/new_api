#!/usr/bin/env python3

import requests
import ujson as json
import falcon
import helpers
import re

class Connector:

    def __init__(self):
        self.s = requests.Session()
        s = requests.Session()

    def query_es(self,req):

        # Set up parameters for call
        params = {}
        if 'subreddit' in req.params:
            params['routing'] = ','.join(req.params['subreddit'])

        if req.context['type'] == 'comment':
            index = "rc"
        elif req.context['type'] == 'submission':
            index = "rs"

        # Check if a custom index has been passed and if it is valid
        if 'index' in req.params:
            if not re.match(r"r[rcs]_\d\d\d\d-q\d\d",req.params['index']):
                raise falcon.HTTPUnprocessableEntity(description="The index parameter accepts the following pattern rc_YYYY-q01")
            if req.params['index'].startswith('rc_') and req.context['type'] == 'submission':
                raise falcon.HTTPUnprocessableEntity(description="You are attempting to use a comment index for a submission search.  Did you mean rc_ instead of rs_?")
            if req.params['index'].startswith('rs_') and req.context['type'] == 'comment':
                raise falcon.HTTPUnprocessableEntity(description="You are attempting to use a submission index for a comment search.  Did you mean rs_ instead of rc_?")
            index = req.params['index']

        uri = "http://localhost:9200/{}/{}s/_search".format(index,req.context['type'])
        headers = {'Content-Type': 'application/json','Accept-Encoding': 'deflate, compress, gzip'}
        response = self.s.get(uri, params=params, data=json.dumps(req.context['es_query']), headers=headers)
        status_code = str(response.status_code)
        if not status_code.startswith('2'):
            raise falcon.HTTPInternalServerError(title="Internal Error from Elasticsearch",
                                                description="{}".format(response.content.decode('utf8')))
        else:
            es_data = json.loads(response.content)

            # Process hits Returned From ES
            if 'hits' in es_data:
                hits = es_data['hits'].pop('hits')
                req.context['data'] = []
                for hit in hits:
                    obj = hit['_source']
                    obj['id'] = helpers.base36encode(int(hit['_id']))
                    obj['base10_id'] = int(hit['_id'])
                    req.context['data'].append(obj)

            # Process Aggregations
            if 'aggregations' in es_data:
                req.context['aggs'] = {}
                for key in es_data['aggregations']:
                    buckets = es_data['aggregations'][key].pop('buckets',None)
                    req.context['aggs'][key] = es_data['aggregations'][key]
                    if buckets is not None:
                        if key == 'created_utc':
                            for idx,bucket in enumerate(buckets):
                                buckets[idx]['key'] = buckets[idx]['key'] // 1000
                        req.context['aggs'][key]['buckets'] = []
                        req.context['aggs'][key]['buckets'] = buckets

            req.context['metadata'] = {}
            meta = req.context['metadata']
            es = meta['elasticsearch'] = {}
            es['took'] = es_data['took']
            es['timed_out'] = es_data['timed_out']
            es['shards'] = es_data['_shards']
            es['hits'] = es_data['hits']
