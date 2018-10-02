import ujson as json
import falcon


def Process(obj,req):

    if isinstance(req.params['aggregation'],str):
        req.params['aggregation'] = [req.params['aggregation']]

    for agg in req.params['aggregation']:

        nested_aggs = agg.split(".")
        agg = nested_aggs[0].lower()

        if agg == 'created_utc':
            req.context['es_query']['aggs']['created_utc']['date_histogram']['field'] = "created_utc"
            if 'frequency' not in req.params:
                req.params['frequency'] = "day"
            req.context['es_query']['aggs']['created_utc']['date_histogram']['interval'] = req.params['frequency']
            req.context['es_query']['aggs']['created_utc']['date_histogram']['order']['_key'] = "asc"
            if len(nested_aggs) >= 3:
                req.context['es_query']['aggs']['created_utc']['aggs'][nested_aggs[1]][nested_aggs[1]]['field'] = nested_aggs[2]
                if nested_aggs[1] == "cardinality":
                    req.context['es_query']['aggs']['created_utc']['aggs'][nested_aggs[1]][nested_aggs[1]]['precision_threshold'] = 40000

        if agg in ['author','subreddit','domain']:
            req.context['es_query']['aggs'][agg]['terms']['field'] = agg
            req.context['es_query']['aggs'][agg]['terms']['size'] = req.params['aggregation.size']
            if 'aggregation.shard_size' in req.params:
                req.context['es_query']['aggs'][agg]['terms']['shard_size'] = req.params['aggregation.shard_size']
            req.context['es_query']['aggs'][agg]['terms']['order']['_count'] = 'desc'

        if agg == 'domain':
            req.context['es_query']['aggs'][agg]['terms']['field'] = 'domain.keyword'
            req.context['es_query']['aggs'][agg]['terms']['size'] = req.params['aggregation.size']
            if 'aggregation.shard_size' in req.params:
                req.context['es_query']['aggs'][agg]['terms']['shard_size'] = req.params['aggregation.shard_size']
            req.context['es_query']['aggs'][agg]['terms']['order']['_count'] = 'desc'

