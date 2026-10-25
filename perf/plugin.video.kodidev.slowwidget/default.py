"""Random movies from the library, delivered after ?delay= seconds (default 8)."""
import json
import sys
import time
from urllib.parse import parse_qsl

import xbmc
import xbmcgui
import xbmcplugin

handle = int(sys.argv[1])
params = dict(parse_qsl(sys.argv[2].lstrip('?')))
time.sleep(float(params.get('delay', 8)))

request = {'jsonrpc': '2.0', 'id': 1, 'method': 'VideoLibrary.GetMovies', 'params': {
    'properties': ['title', 'plot', 'art', 'file', 'runtime'],
    'sort': {'method': 'random'}, 'limits': {'end': 10}}}
movies = json.loads(xbmc.executeJSONRPC(json.dumps(request))).get('result', {}).get('movies', [])
for movie in movies:
    item = xbmcgui.ListItem(movie['title'])
    item.setArt(movie.get('art', {}))
    tag = item.getVideoInfoTag()
    tag.setMediaType('movie')
    tag.setTitle(movie['title'])
    tag.setPlot(movie.get('plot', ''))
    tag.setDuration(movie.get('runtime', 0))
    tag.setDbId(movie['movieid'])
    xbmcplugin.addDirectoryItem(handle, movie['file'], item)
xbmcplugin.setContent(handle, 'movies')
xbmcplugin.endOfDirectory(handle)
