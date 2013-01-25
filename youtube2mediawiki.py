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
import re
import shutil
import tempfile
import urllib2
from urllib import unquote_plus
import webbrowser
from xml.dom.minidom import parseString


__version__ = 0.2

DEBUG=1
USER_AGENT='youtube2mediawiki/%s (+http://www.mediawiki.org/wiki/User:BotInc/youtube2mediawiki)' % __version__
DESCRIPTION = '''
=={{int:filedesc}}==
{{Information
|description=%(description)s
|source=%(url)s
|author=%(author)s
|date=%(date)s
|permission=
|other_versions=
}}

== {{int:license}} ==
{{cc-by-sa-3.0}}{{LicenseReview}}

[[Category:Uploaded with youtube2mediawiki]]
%(wiki_categories)s
'''

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
	        ('User-Agent',
	         'Mozilla/5.0 (X11; Linux i686; rv:2.0) Gecko/20100101 Firefox/4.0'),
            ('Accept-Language', 'en-us, en;q=0.50')
        ]

    def info(self, id):
        info = {}
        url = "http://gdata.youtube.com/feeds/api/videos/%s?v=2" % id
        u = self.opener.open(url)
        data = u.read()
        u.close()
        xml = parseString(data)
        info['url'] = 'http://www.youtube.com/watch?v=%s'%id
        info['title'] = xml.getElementsByTagName('title')[0].firstChild.data
        info['description'] = xml.getElementsByTagName('media:description')[0].firstChild.data
        info['date'] = xml.getElementsByTagName('published')[0].firstChild.data.split('T')[0]
        info['author'] = "http://www.youtube.com/user/%s"%xml.getElementsByTagName('name')[0].firstChild.data

        info['categories'] = []
        for cat in xml.getElementsByTagName('media:category'):
            info['categories'].append(cat.firstChild.data)

        info['keywords'] = []
        keywords = xml.getElementsByTagName('media:keywords')[0].firstChild
        if keywords:
            info['keywords'] = keywords.data.split(', ')
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

    def download(self, id, filename):
        stream_type = 'video/webm'
        url = "http://www.youtube.com/watch?v=%s" % id
        u = self.opener.open(url)
        data = u.read()
        u.close()
        match = re.compile('"url_encoded_fmt_stream_map": "(.*?)"').findall(data)
        streams = {}
        for x in match[0].split(','):
            stream = {}
            for s in x.split('\\u0026'):
                key, value = s.split('=')
                value = unquote_plus(value)
                stream[key] = value
            if stream['type'].startswith(stream_type):
                streams[stream['itag']] = stream
        if streams:
            s = max(streams.keys())
            url = '%s&signature=%s' % (streams[s]['url'], streams[s]['sig'])
        else:
            print "no WebM video found"
            return False

        #download video and save to file.
        u = self.opener.open(url)
        f = open(filename, 'w')
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
            form.add_file(key, os.path.basename(files[key]), open(files[key]))
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
        return str(self.api('query', {
            'prop': 'info',
            'titles': page,
            'intoken': intoken
        })['query']['pages']['-1']['edittoken'])

    def upload(self, filename, description, text):
        fn = os.path.basename(filename)
        pagename = 'File:' + fn.replace(' ', '_')
        token = self.get_token(pagename, 'edit')
        return self.api('upload', {
            'comment': description,
            'text': text,
            'filename': fn,
            'token': token
        }, {'file': filename})

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
    s = s.replace('__', '_').replace('__', '_')
    return s

def import_youtube(youtube_id, username, password, mediawiki_url):
    yt = Youtube()
    wiki = Mediawiki(mediawiki_url, username, password)
    info = yt.info(youtube_id)
    d = tempfile.mkdtemp()
    filename = os.path.join(d, u"%s.webm" % safe_name(info['title']))
    description = DESCRIPTION % info
    if yt.download(youtube_id, filename):
        r = wiki.upload(filename, 'Imported from %s'%info['url'], description)
        if r['upload']['result'] == 'Success':
            result_url = r['upload']['imageinfo']['descriptionurl']
            languages = yt.subtitle_languages(youtube_id)
            for lang in languages:
                srt = yt.subtitles(youtube_id, lang)
                if srt:
                    name = u'TimedText:%s.%s.srt' % (
                        os.path.basename(filename).replace(' ', '_'),
                        lang
                    )
                    r = wiki.edit_page(name, srt, 'Imported from %s'%info['url'])
            print 'Uploaded to', result_url
        else:
            print 'Upload failed.'
    else:
        print 'Download failed.'
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
    parser.add_option('-p', '--password', dest='password', help='wiki password', type='string')
    parser.add_option('-w', '--url', dest='url', help='wiki api url [default:http://commons.wikimedia.org/w/api.php]',
                      default='http://commons.wikimedia.org/w/api.php', type='string')
    (opts, args) = parser.parse_args()

    if None in (opts.username, opts.password) or not args:
        parser.print_help()
        sys.exit(-1)

    youtube_id = parse_id(args[0])
    import_youtube(youtube_id, opts.username, opts.password, opts.url)

