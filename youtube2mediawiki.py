#!/usr/bin/env python
# -*- coding: utf-8 -*-
# vi:si:et:sw=4:sts=4:ts=4
# MIT 2011
import cookielib
from htmlentitydefs import name2codepoint
import itertools
import json
import mimetools
import mimetypes
import os
import platform
import re
import shutil
import subprocess
import tempfile
import traceback
import urllib2
from urllib import unquote_plus
import webbrowser
from xml.dom.minidom import parseString
from StringIO import StringIO


__version__ = 0.4

DEBUG=False
IGNORE_WARNINGS=False
MERGE_DASH=False
OVERWRITE=False
USER_AGENT='youtube2mediawiki/%s (+http://www.mediawiki.org/wiki/User:BotInc/youtube2mediawiki)' % __version__
YOUTUBE_USER_AGENT='Mozilla/5.0 (X11; Linux i686; rv:38.0) Gecko/20100101 Firefox/38.0'
DESCRIPTION = '''=={{int:filedesc}}==
{{Information
|description=%(description)s
|source=%(url)s
|author=%(author)s
|date=%(date)s
|permission=
|other_versions=
}}

== {{int:license-header}} ==
{{YouTube CC-BY}}
{{LicenseReview}}

[[Category:Uploaded with youtube2mediawiki]]
%(wiki_categories)s
'''
VIDEO_QUALITY = [ # Higher index -> "better" quality
                '278',
                '242',
                '167',
                '243',
                '168',
                '218',
                '219',
                '244',
                '245',
                '246',
                '169',
                '247',
                '302',
                '170',
                '248',
                '303',
                '271',
                '308',
                '272',
                '313',
                '315']
AUDIO_QUALITY = [ # Higher index -> "better" quality
                '171',
                '249',
                '250',
                '172',
                '251']

# This pattern matches a character entity reference (a decimal numeric
# references, a hexadecimal numeric reference, or a named reference).
charrefpat = re.compile(r'&(#(\d+|x[\da-fA-F]+)|[\w.:-]+);?')

def decode_html(html):
    """
    >>> decodeHtml('me &amp; you and &#36;&#38;%')
    u'me & you and $&%'
    """
    if type(html) != unicode:
        html = unicode(html)[:]
    if type(html) is unicode:
        uchr = unichr
    else:
        uchr = lambda value: value > 255 and unichr(value) or chr(value)
    def entitydecode(match, uchr=uchr):
        entity = match.group(1)
        if entity.startswith('#x'):
            return uchr(int(entity[2:], 16))
        elif entity.startswith('#'):
            return uchr(int(entity[1:]))
        elif entity in name2codepoint:
            return uchr(name2codepoint[entity])
        else:
            return match.group(0)
    return charrefpat.sub(entitydecode, html).replace(u'\xa0', ' ')

def format_time(seconds):
    ms = int(seconds * 1000)
    h = int(ms % 86400000 / 3600000)
    m = int(ms % 3600000 / 60000)
    s = int(ms % 60000 / 1000)
    ms = ms % 1000
    return "%02d:%02d:%02d,%03d" % (h, m, s, ms)

class Youtube:
    '''
    Example:
        yt = Youtube()
        yt.downlaod(id, filename)
    '''
    def __init__(self):
        self.cj = cookielib.CookieJar()
        self.opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(self.cj))
        self.opener.addheaders = [
            ('User-Agent', YOUTUBE_USER_AGENT),
            ('Accept-Language', 'en-us, en;q=0.50')
        ]

    def info(self, id):
        def get_data(e):
            return e.firstChild and e.firstChild.data or ''
        info = {}
        url = "http://gdata.youtube.com/feeds/api/videos/%s?v=2" % id
        u = self.opener.open(url)
        data = u.read()
        u.close()
        xml = parseString(data)
        info['url'] = 'http://www.youtube.com/watch?v=%s'%id
        info['title'] = get_data(xml.getElementsByTagName('title')[0])
        info['description'] = get_data(xml.getElementsByTagName('media:description')[0])
        info['date'] = xml.getElementsByTagName('published')[0].firstChild.data.split('T')[0]
        info['author'] = "https://www.youtube.com/user/%s"%xml.getElementsByTagName('uri')[0].firstChild.data.split('/')[-1]

        info['categories'] = []
        for cat in xml.getElementsByTagName('media:category'):
            info['categories'].append(cat.firstChild.data)

        info['keywords'] = []
        keywords = get_data(xml.getElementsByTagName('media:keywords')[0])
        if keywords:
            info['keywords'] = keywords.split(', ')
        info['wiki_categories'] = '\n'.join(['[[Category:%s]]'%c for c in info['categories']])

        url = "http://www.youtube.com/watch?v=%s" % id
        u = self.opener.open(url)
        data = u.read()
        u.close()
        match = re.compile('<h4>License:</h4>(.*?)</p>', re.DOTALL).findall(data)
        if match:
            info['license'] = match[0].strip()
            info['license'] = re.sub('<.+?>', '', info['license']).strip()
        return info

    def subtitle_languages(self, id):
        url = "http://www.youtube.com/api/timedtext?hl=en&type=list&tlangs=1&v=%s&asrs=1"%id
        u = self.opener.open(url)
        data = u.read()
        u.close()
        xml = parseString(data)
        return [t.getAttribute('lang_code') for t in xml.getElementsByTagName('track')]

    def subtitles(self, id, language='en'):
        url = "http://www.youtube.com/api/timedtext?hl=en&v=%s&type=track&lang=%s&name&kind"%(id, language)
        u = self.opener.open(url)
        data = u.read()
        u.close()
        xml = parseString(data)
        srt = u''
        n = 0
        for t in xml.getElementsByTagName('text'):
            start = float(t.getAttribute('start'))
            duration = t.getAttribute('dur')
            if not duration:
                duration = '2'
            end = start + float(duration)
            text = t.firstChild.data
            srt += u'%s\n%s --> %s\n%s\n\n' % (
                    n, 
                    format_time(start),
                    format_time(end),
                    decode_html(text))
            n += 1
        return srt

    def find_max(self, keys, quality):
        max_itag_index = -1
        for key in keys:
            if quality.index(key) > max_itag_index:
                max_itag_index = quality.index(key)
        return quality[max_itag_index]

    def get_url(self, stream):
        if 'sig' in stream:
            url = '%s&signature=%s' % (stream['url'], stream['sig'])
        elif 'url' in stream:
            url = stream['url']
        else:
            raise Exception('No download URL found')
        return url

    def get_urls(self, video_streams, audio_streams):
        if not MERGE_DASH: # == not audio_streams
            # for non adaptive streams a higher itag simply means higher quality
            max_v_itag = max(video_streams.keys())
            if DEBUG:
                print ('Getting download url for itag=' + max_v_itag)
            video_url = self.get_url(video_streams[max_v_itag])
            audio_url = '' # audio and video in one file
            return video_url, audio_url
        max_v_itag = self.find_max(video_streams.keys(), VIDEO_QUALITY)
        max_a_itag = self.find_max(audio_streams.keys(), AUDIO_QUALITY)
        if DEBUG:
            print 'Getting download urls for itags=[' + max_v_itag + ', ' + max_a_itag + ']'
        audio_url = self.get_url(audio_streams[max_a_itag])
        video_url = self.get_url(video_streams[max_v_itag])
        return video_url, audio_url

    def download(self, id, *filenames):
        if MERGE_DASH: # == len(filenames)==2
             format_map_regex = '"adaptive_fmts".*?"(.*?)"'
        else: # len(filenames)==1:
             format_map_regex = '"url_encoded_fmt_stream_map".*?"(.*?)"'
        video_stream_type = 'video/webm'
        audio_stream_type = 'audio/webm'
        unavailable_message = '<h1 id="unavailable-message" class="message">'
        url = "http://www.youtube.com/watch?v=%s" % id
        u = self.opener.open(url)
        data = u.read()
        u.close()
        match = re.compile(format_map_regex).findall(data)
        if not match and unavailable_message in data:
            raise Exception("YouTube video not available")
        video_streams = {}
        audio_streams = {}
        for x in match[0].split(','):
            stream = {}
            for s in x.split('\\u0026'):
                key, value = s.split('=')
                value = unquote_plus(value)
                stream[key] = value
            if stream['type'].startswith(video_stream_type):
                video_streams[stream['itag']] = stream
            if stream['type'].startswith(audio_stream_type) and MERGE_DASH:
                audio_streams[stream['itag']] = stream
        if video_streams: # and not (audio_streams xor MERGE_DASH)
            urls = self.get_urls(video_streams, audio_streams)
        else:
            raise Exception('No WebM video found')

        #download stream and save to file.
        for i, url in enumerate(urls):
            if not url:
                break
            u = self.opener.open(url)
            f = open(filenames[i], 'w')
            data = True
            while data:
                data = u.read(4096)
                f.write(data)
            f.close()
            u.close()
        return True

class MultiPartForm(object):
    """Accumulate the data to be used when posting a form."""

    def __init__(self):
        self.form_fields = []
        self.files = []
        self.boundary = mimetools.choose_boundary()
        return
    
    def get_content_type(self):
        return 'multipart/form-data; boundary=%s' % self.boundary

    def add_field(self, name, value):
        """Add a simple field to the form data."""
        if isinstance(name, unicode):
            name = name.encode('utf-8')
        if isinstance(value, unicode):
            value = value.encode('utf-8')
        self.form_fields.append((name, value))
        return

    def add_file(self, fieldname, filename, fileHandle, mimetype=None):
        """Add a file to be uploaded."""
        if isinstance(fieldname, unicode):
            fieldname = fieldname.encode('utf-8')
        if isinstance(filename, unicode):
            filename = filename.encode('utf-8')
        if hasattr(fileHandle, 'read'):
            body = fileHandle.read()
        else:
            body = fileHandle
        if mimetype is None:
            mimetype = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
        self.files.append((fieldname, filename, mimetype, body))
        return
    
    def __str__(self):
        """Return a string representing the form data, including attached files."""
        # Build a list of lists, each containing "lines" of the
        # request.  Each part is separated by a boundary string.
        # Once the list is built, return a string where each
        # line is separated by '\r\n'.  
        parts = []
        part_boundary = '--' + self.boundary
        
        # Add the form fields
        parts.extend(
            [ part_boundary,
              'Content-Disposition: form-data; name="%s"' % name,
              '',
              value,
            ]
            for name, value in self.form_fields
            )
        
        # Add the files to upload
        parts.extend(
            [ part_boundary,
              'Content-Disposition: file; name="%s"; filename="%s"' % \
                 (field_name, filename),
              'Content-Type: %s' % content_type,
              '',
              body,
            ]
            for field_name, filename, content_type, body in self.files
            )
        
        # Flatten the list and add closing boundary marker,
        # then return CR+LF separated data
        flattened = list(itertools.chain(*parts))
        flattened.append('--' + self.boundary + '--')
        flattened.append('')
        return '\r\n'.join(flattened)

class Mediawiki(object):
    def __init__(self, url, username, password):
        self.url = url
        self.username = username
        self.password = password

        self.cj = cookielib.CookieJar()
        self.opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(self.cj),
                                           urllib2.HTTPHandler(debuglevel=0))
        self.opener.addheaders = [
            ('User-Agent', USER_AGENT)
        ]
        r = self.login()
        if not r['login']['result'] == 'Success':
            if DEBUG:
                print r
            raise Exception('login failed')

    def post(self, form):
        try:
            request = urllib2.Request(self.url)
            body = str(form)
            request.add_header('Content-type', form.get_content_type())
            request.add_header('Content-length', len(body))
            request.add_data(body)
            result = self.opener.open(request).read().strip()
            return json.loads(result)
        except urllib2.HTTPError, e:
            if DEBUG:
                if e.code >= 500:
                    with open('/tmp/error.html', 'w') as f:
                        f.write(e.read())
                    webbrowser.open_new_tab('/tmp/error.html')
            result = e.read()
            try:
                result = json.loads(result)
            except:
                result = {'status':{}}
            result['status']['code'] = e.code
            result['status']['text'] = str(e)
            return result

    def api(self, action, data={}, files={}):
        form = MultiPartForm()
        form.add_field('format', 'json')
        form.add_field('action', action)
        for key in data:
            form.add_field(key, data[key])
        for key in files:
            if isinstance(files[key], basestring):
                form.add_file(key, os.path.basename(files[key]), open(files[key]))
            else:
                form.add_file(key, 'data.bin', files[key])
        return self.post(form)

    def login(self):
        form = MultiPartForm()
        form.add_field('format', 'json')
        form.add_field('action','login')
        form.add_field('lgname', self.username)
        form.add_field('lgpassword', self.password)
        r = self.post(form)
        self.token = r['login']['token']
        self.sessionid = r['login']['sessionid']
        return self.api('login', {
            'lgname': self.username,
            'lgpassword': self.password,
            'lgtoken': self.token
        })

    def get_token(self, page, intoken='edit'):
        r = self.api('query', {
            'prop': 'info',
            'titles': page,
            'intoken': intoken
        })['query']['pages']
        return '-1' in r and str(r['-1']['edittoken']) or \
               OVERWRITE and str(r.items()[0][1]['edittoken']) or \
               None

    def upload(self, filename, description, text, name=''):
        CHUNKSIZE = 5*1024*1024
        offset = 0
        if len(name) > 0:
            name = re.sub(re.compile('^File:', re.IGNORECASE), '', name)
            name = re.sub(re.compile('\.webm$', re.IGNORECASE), '', name) + '.webm'
        fn = name or os.path.basename(filename)
        pagename = 'File:' + fn.replace(' ', '_')
        token = self.get_token(pagename, 'edit')
        if not token:
            raise Exception("%s exists, can not upload" % pagename)
        chunk = StringIO()
        filesize = os.stat(filename).st_size
        f = open(filename)
        f.seek(offset)
        chunk.write(f.read(CHUNKSIZE))
        f.close()
        chunk.seek(0)
        #Upload first chunk and get filekey for further chunks
        args_upload = {
            'comment': description,
            'filename': fn,
            'filesize': str(filesize),
            'offset': str(offset),
            'token': token
        }
        if IGNORE_WARNINGS:
            args_upload['ignorewarnings'] = ''
        r = self.api('upload', args_upload, {'chunk': chunk})
        offset += CHUNKSIZE
        if 'error' in r:
            if DEBUG:
                if 'info' in r['error']:
                    print r['error']['info']
                else:
                    print r['error']
            raise Exception("Upload error") # return r
        filekey = r['upload']['filekey']
        while offset < filesize:
            if DEBUG:
                print r
            if 'error' in r or r.get('status', {}).get('code', 200) != 200 or \
                'error' in r.get('upload', {}):
                raise Exception("Upload error") # return r
            chunk = StringIO()
            f = open(filename)
            f.seek(offset)
            chunk.write(f.read(CHUNKSIZE))
            f.close()
            chunk.seek(0)
            #Upload chunk at offset
            args_upload = {
                'filename': fn,
                'filesize': str(filesize),
                'offset': str(offset),
                'filekey': filekey,
                'token': token
            }
            if IGNORE_WARNINGS:
                args_upload['ignorewarnings'] = ''
            r = self.api('upload', args_upload, {'chunk': chunk})
            if filekey != r['upload']['filekey']:
                if DEBUG:
                    print 'WARNING: filekey changed:', filekey , r['upload']['filekey']
                filekey = r['upload']['filekey']

            offset += CHUNKSIZE
        #Finalize upload and move out of stash
        args_upload = {
            'filename': fn,
            'filekey': filekey,
            'token': token,
            'text': text,
            'comment': description
        }
        if IGNORE_WARNINGS:
            args_upload['ignorewarnings'] = ''
        r = self.api('upload', args_upload)
        if DEBUG:
            print r
        if r and r.get('upload', {}).get('result') == 'Success':
            result_url = r['upload']['imageinfo']['descriptionurl']
            return result_url
        else:
            raise Exception("Upload error during finalize")

    def edit_page(self, pagename, text, comment=''):
        token = self.get_token(pagename, 'edit')
        return self.api('edit', {
            'comment': comment,
            'text': text,
            'title': pagename,
            'token': token
        })

def safe_name(s):
    s = s.strip()
    s = s.replace(' ', '_')
    s = re.sub(r'[:/\\]', '_', s)
    s = re.sub(r'[<>\[\]\|\{\}$#"\/]', '-', s)
    s = s.replace('__', '_').replace('__', '_')
    return s

def ffmpeg_installed():
    if (platform.system() == 'Linux' or platform.system() == 'Darwin'):
        find_cmd = 'which'
        ffmpeg = 'ffmpeg'
    else: #platform.system() == 'Windows'
        find_cmd = 'where'
        ffmpeg = 'ffmpeg.exe'

    if DEBUG:
        print 'Testing for ' + ffmpeg + ' on ' + platform.system()

    try:
        if 0 != subprocess.call([find_cmd, ffmpeg], stdout=open(os.devnull, 'wb'), stderr=subprocess.STDOUT):
            ffmpeg = './' + ffmpeg
        if 0 == subprocess.call([ffmpeg, '-version'], stdout=open(os.devnull, 'wb'), stderr=subprocess.STDOUT):
            return ffmpeg
    except Exception:
        pass

    if DEBUG:
        print 'Install ffmpeg or place ' + ffmpeg + ' in the current working directory (' + os.getcwd() + ')'
    raise Exception("ffmpeg not found")

def import_youtube(youtube_id, username, password, mediawiki_url, name=''):
    yt = Youtube()
    if MERGE_DASH:
        ffmpeg = ffmpeg_installed()
    wiki = Mediawiki(mediawiki_url, username, password)
    info = yt.info(youtube_id)
    d = tempfile.mkdtemp()
    filename = os.path.join(d, u"%s.webm" % safe_name(info['title']))
    description = DESCRIPTION % info
    result_url = None
    try:
        if MERGE_DASH:
            filename_video = os.path.join(d, "video.dat")
            filename_audio = os.path.join(d, "audio.dat")
            yt.download(youtube_id, filename_video, filename_audio)
            if not ( 0 == subprocess.call([ffmpeg, "-i", filename_video, "-i", filename_audio, "-c:v", "copy", "-c:a", "copy", filename], stdout=open(os.devnull, 'wb'), stderr=subprocess.STDOUT) ):
                raise Exception('merge by ffmpeg failed')
        else:
            yt.download(youtube_id, filename)

        new_version = 'new version ' if OVERWRITE else ''
        result_url = wiki.upload(filename, 'Imported %sfrom %s using youtube2mediawiki version %s '%(new_version, info['url'], __version__), description, name)
        
        languages = '' if OVERWRITE else yt.subtitle_languages(youtube_id)
        for lang in languages:
            srt = yt.subtitles(youtube_id, lang)
            if srt:
                subtitle_name = u'TimedText:%s.%s.srt' % (
                    (name or os.path.basename(filename)).replace(' ', '_'),
                    lang
                )
                r = wiki.edit_page(subtitle_name, srt, 'Imported from %s'%info['url'])
    finally:
        if result_url:
            print 'Uploaded to', result_url
        shutil.rmtree(d)

def parse_id(url):
    match = re.compile('\?v=([^&]+)').findall(url)
    if match:
        return match[0]
    return url

if __name__ == "__main__":
    from optparse import OptionParser
    import sys

    usage = "Usage: %prog [options] youtubeid"
    parser = OptionParser(usage=usage)
    parser.add_option('-u', '--username', dest='username', help='wiki username', type='string')
    parser.add_option('-p', '--password', dest='password', help='wiki password\n(can also be provided via Y2M_PASSWORD environment variable)', type='string')
    parser.add_option('-w', '--url', dest='url', help='wiki api url [default:http://commons.wikimedia.org/w/api.php]',
                      default='http://commons.wikimedia.org/w/api.php', type='string')
    parser.add_option('-n', '--name', dest='name', help='name of file on wiki, by default title on youtube is used', type='string', default='')
    parser.add_option('-d', '--debug', dest='debug', help='output debug information', action="store_true")
    parser.add_option('-i', '--ignore-warnings', dest='ignorewarnings', help='ignore warnings during upload', action="store_true")
    parser.add_option('-a', '--adaptive-streaming', dest='vp9', help='fetch HD VP9 stream + audio stream and merge both using ffmpeg', action="store_true")
    parser.add_option('-o', '--overwrite', dest='overwrite', help='force overwriting files at the destination wiki (requires --ignore-warnings)', action="store_true")
    (opts, args) = parser.parse_args()
    if not opts.password:
        opts.password = os.environ.get('Y2M_PASSWORD')

    if None in (opts.username, opts.password) or not args:
        parser.print_help()
        sys.exit(-1)

    DEBUG = opts.debug
    IGNORE_WARNINGS = opts.ignorewarnings
    MERGE_DASH = opts.vp9
    OVERWRITE = opts.overwrite
    youtube_id = parse_id(args[0])
    try:
        import_youtube(youtube_id, opts.username, opts.password, opts.url, opts.name)
    except Exception as e:
        if not DEBUG:
            print e
            print "Exception caught! Consider using the --debug option to identify the issue."
        else:
            traceback.print_exc()
