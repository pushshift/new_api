import falcon
from collections import defaultdict
#from Helpers import *
from falcon import uri
import requests
import ujson as json
import aggregations
import calendar
import datetime
import time
import re
from helpers import *

def Process(obj,req):

    suggested_sort = "desc"

    # Set up elasticsearch query dict
    nested_dict = lambda: defaultdict(nested_dict)
    req.context['es_query'] = nested_dict()
    es_query = req.context['es_query']

    # Filter Context
    es_query['query']['bool']['filter']['bool']['must'] = []
    es_query['query']['bool']['filter']['bool']['should'] = []
    es_query['query']['bool']['filter']['bool']['must_not'] = []
    es_query['query']['bool']['filter']['bool']['filter'] = []

    # Query Context
    es_query['query']['bool']['must'] = []
    es_query['query']['bool']['should'] = []
    es_query['query']['bool']['must_not'] = []

    # Handle boolean type conditions
    conditions = [  "is_bot","was_stickied","is_submitter","is_edited","show_media_preview","user_sr_theme_enabled","wiki_enabled","hide_ads",
                    "allow_videos","allow_images","allow_videogifs","is_enrolled_in_new_modmail","spoilers_enabled","quarantine","pinned",
                    "is_reddit_media_domain","can_gild","can_mod_post","is_original_content","no_follow","send_replies","has_quote","is_self",
                    "over_18","is_video","stickied","spoiler","locked","contest_mode","is_crosspostable","brand_safe","over18"]
    for condition in conditions:
        if condition in req.params and req.params[condition] is not None:
            parameter = nested_dict()
            if req.params[condition] == True:
                parameter['term'][condition] = True
            elif req.params[condition] == False:
                parameter['term'][condition] = False
            es_query['query']['bool']['must'].append(parameter)

    # Process before and after parameters

    date_pattern = re.compile("^\d\d\d\d-\d\d-\d\d")
    date_time_pattern = re.compile("^\d\d\d\d-\d\d-\d\d \d\d:\d\d:\d\d")

    for key in ['before','after']:

        if key in req.params and req.params[key] is not None:
            if date_time_pattern.match(req.params[key]):
                req.params[key] = calendar.timegm(time.strptime(req.params[key], '%Y-%m-%d %H:%M:%S'))
            elif date_pattern.match(req.params[key]):
                req.params[key] = calendar.timegm(time.strptime(req.params[key], '%Y-%m-%d'))
            elif LooksLikeInt(req.params[key]):
                req.params[key] = int(req.params[key])
            elif req.params[key][-1:].lower() == "d":
                req.params[key] = int(time.time()) - (int(req.params[key][:-1]) * 86400)
            elif req.params[key][-1:].lower() == "h":
                req.params[key] = int(time.time()) - (int(req.params[key][:-1]) * 3600)
            elif req.params[key][-1:].lower() == "m":
                req.params[key] = int(time.time()) - (int(req.params[key][:-1]) * 60)
            elif req.params[key][-1:].lower() == "s":
                req.params[key] = int(time.time()) - (int(req.params[key][:-1]))
            range = nested_dict()
            if key == 'after':
                range['range']['created_utc']['gt'] = req.params[key]
            elif key == 'before':
                range['range']['created_utc']['lt'] = req.params[key]
            es_query['query']['bool']['filter']['bool']['filter'].append(range)
            if key == 'after':
                suggested_sort = "asc"
        else:
            req.params[key] = None

    if 'link_id' in req.params:
        if not isinstance(req.params['link_id'],list):
            req.params['link_id'] = req.params['link_id'].split(',')
        for i,lid in enumerate(req.params['link_id'][:]):
            req.params['link_id'][i] = lid.lower()
            if lid[:3] == "t3_":
                req.params['link_id'][i] = lid[3:]
            req.params['link_id'][i] = str(int(req.params['link_id'][i],36))

    conditions = ["subreddit","author","domain","link_id"]
    for condition in conditions:
        if condition in req.params:
            req.params[condition] = uri.decode(req.params[condition])
            if not isinstance(req.params[condition], (list, tuple)):
                req.params[condition] = req.params[condition].split(",")
            param_values = [x.lower() for x in req.params[condition]]
            # Need to make this a function for when users request to be removed from API
            if condition == "author":
                while 'bilbo-t-baggins' in param_values: param_values.remove('bilbo-t-baggins')
            terms = nested_dict()
            if req.params[condition][0][0] == "!":
                terms['terms'][condition] = list(map(lambda x:x.replace("!",""),param_values))
                es_query['query']['bool']['must_not'].append(terms)
            else:
                terms['terms'][condition] = param_values
                es_query['query']['bool']['filter']['bool']['must'].append(terms)

    if 'sort_type' in req.params and req.params['sort_type'] is not None:
        req.params["sort_type"] = req.params['sort_type'].lower()
    else:
        req.params["sort_type"] = "created_utc"

    if 'sort' in req.params:
        if ":" in req.params['sort']:
            req.params['sort_type'], req.params['sort'] = req.params['sort'].split(":")
        else:
            req.params['sort'] = req.params['sort'].lower()
        if req.params['sort'] != "asc" and req.params['sort'] != "desc":
            req.params['sort'] = suggested_sort
    else:
        req.params['sort'] = suggested_sort
    es_query['sort'][req.params['sort_type']] = req.params['sort']

    # Process the size parameter.  If aggregation is requested and size is not specified, default
    # size to 0 (aggregation results only -- no ES doc hits)
    if 'size' in req.params:
        es_query['size'] = req.params['size']
    else:
        if 'aggregation' not in req.params:
            es_query['size'] = int(obj.param_info['size']['default'])
        else:
            es_query['size'] = 0

    # Process Aggregations if present
    if 'aggregation' in req.params:
        if 'aggregation.size' not in req.params:
            req.params['aggregation.size'] = int(obj.param_info['aggregation.size']['default'])
        #if 'aggregation.shard_size' not in req.params:
        #    req.params['aggregation.shard_size'] = int(obj.param_info['aggregation.shard_size']['default'])

        aggregations.Process(obj,req)

    #req.context['es_query'] = es_query
