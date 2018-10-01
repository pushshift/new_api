import io
import os
import ast
import operator
import time
import datetime
import calendar
import ujson as json
import sys
from textwrap import wrap
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import matplotlib.dates as mdates
from mpl_toolkits.mplot3d import Axes3D
from matplotlib.ticker import MultipleLocator
from pylab import savefig
import numpy as np
import imageio
import uuid
import html
#import spacy
import pytz
import falcon
from wordcloud import WordCloud
from collections import defaultdict


def create_timeline(req):

    data = req.context['aggs']['created_utc']['buckets']

    if len(data) < 2:
        return

    if 'chart.trim' in req.params and req.params['chart.trim']:
        del data[0]
        del data[-1]

    x = [datetime.datetime.fromtimestamp(int(z['key']),tz=pytz.utc) for z in data]

    agg_components = req.params['aggregation'][0].split('.')
    if len(agg_components) >= 3:
        if len(agg_components) == 4:
            value = agg_components[3]
        else:
            value = 'value'
        y = [z[agg_components[1]][value] for z in data]
    else:
        y = [int(z['doc_count']) for z in data]
    y_pos = np.arange(len(y))
    fig = plt.figure(figsize=(6,3),dpi=200)

    ax = plt.gca()
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    if 'chart.log' in req.params and req.params['chart.log'] is True:
        ax.set_yscale('log')

    if 'chart.ymin' in req.params:
        ax.set_ylim(bottom=int(req.params['chart.ymin']))
        ax.set_ylim(ymax=max([v for v in y if v is not None])*1.4)

    if 'chart.ymax' in req.params:
        ax.set_ylim(ymax=int(req.params['chart.ymax']))

    ax.yaxis.grid(True,color='#CCCCCC',linestyle='--')
    ax.xaxis.grid(False)

    #ax.xaxis.set_major_locator(months)
    #ax.xaxis.set_minor_locator(days)


    #ax.set_xticks(x)

    opts = {}

    if 'plot_options' in req.params:
        opts = ast.literal_eval(req.params['plot_options'])

    if 'color' not in opts:
        opts['color'] = '#1f77b4'

    xticks = ax.xaxis.get_major_ticks()
    #print(xticks)

    if 'ma' in req.params:
        ma = int(req.params['ma'])
        plt.plot(x,y,color='#a8d1f0')
        plt.plot(x,np.convolve(y,np.ones((ma,))/ma,mode='same'),'#175887')
    else:
        plt.plot(x,y,**opts)


    if 'chart.ylabel' in req.params:
        plt.ylabel(req.params['chart.ylabel'])

    plt.xticks(rotation=-30,fontsize=8,ha='left')
    title_string = ''
    for param in req.params.keys():
        if param not in ['aggs','agg_size','size','type']:
            string = param + ":" + str(req.params[param]) + " "
            title_string += string
    if 'chart.title' in req.params:
        plt.title("\n".join(wrap(req.params['chart.title'], 60)))
    else:
        plt.title("\n".join(wrap(title_string, 80)),fontsize=8,color='#333333')

    plt.tight_layout()

    fig.canvas.draw()       # draw the canvas, cache the renderer
    buf = io.BytesIO()
    savefig(buf, format='png')
    buf.seek(0)
    plt.close(fig)
    plt.close('all')
    return buf

def create_chart(req):

    height = (len(data) * .25)
    if height < 7: height = 7
    fig = plt.figure(figsize=(8,height),dpi=150)

    for key in ['author','subreddit']:
        if key in req.context['aggs']:
            title = key.capitalize()
            data = req.context['aggs'][key]['buckets']
            break
    labels = [x['key'] for x in data[::-1]]
    values = [x['doc_count'] for x in data[::-1]]
    y_pos = np.arange(len(data))

    if 'colormap' in req.params and req.params['colormap'] is not None:
        try:
            colors = getattr(cm,req.params['colormap'])(np.linspace(0.4,0.9,len(data)))
        except:
            raise falcon.HTTPUnprocessableEntity(description="Unknown colormap value.  Please check here for valid colormap values (case-sensitive): https://matplotlib.org/examples/color/colormaps_reference.html")
    else:
        colors = cm.Blues(np.linspace(0.4,0.9,len(data)))

    plt.barh(y_pos, values, align='center', alpha=1,color=colors)

    if 'url' in req.params.get('aggregation'):
        plt.yticks(y_pos,labels,fontsize=7)
    else:
        plt.yticks(y_pos,labels,fontsize=8)

    plt.subplots_adjust(left=0.2)
    title_string = ''

    for param in req.params.keys():
        if param not in ['agg_size','size','type']:
            string = param + ":" + str(req.params[param]) + " "
            title_string += string

    ax = plt.gca()
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_visible(False)
    ax.yaxis.set_tick_params(length=0)

    if 'chart.title' in req.params:
        plt.suptitle('{}'.format(req.params['chart.title']),x=0.55,fontsize=18)
    else:
        plt.suptitle('{} Activity'.format(title),x=0.55,fontsize=18)

    if 'chart.subtitle' in req.params:
        plt.title("\n".join(wrap(req.params['chart.subtitle'], 70)),fontsize=8)
    else:
        plt.title("\n".join(wrap(title_string, 80)),fontsize=8,color='#333333')

    if 'suptitle' in req.params:
        plt.suptitle(req.params['suptitle'],x=0.2,fontsize=18)

    if 'chart.xlabel' in req.params:
        plt.xlabel('{}'.format(req.params['chart.xlabel']))
    else:
        if 'type' in req.context:
            plt.xlabel('Number of {}s'.format(req.context['type'].capitalize()))

    plt.margins(y=0.02)
    fig.tight_layout(rect=[0, 0.03, 1, 0.95])
    fig.canvas.draw()       # draw the canvas, cache the renderer
    buf = io.BytesIO()
    savefig(buf, format='png')
    buf.seek(0)
    # Is this needed?
    plt.close(fig)
    plt.close('all')
    return buf

