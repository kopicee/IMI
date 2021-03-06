#!/usr/bin/env python
# -*- coding: utf-8 -*-
###
### This is a simple cgi-script for showing sentences in the corpus
###
### Copyright Francis Bond 2014 <bond@ieee.org>
### This is released under the CC BY license
### (http://creativecommons.org/licenses/by/3.0/)
### bugfixes and enhancements gratefuly received

import cgi
import cgitb; cgitb.enable()  # for troubleshooting
import re, sqlite3, collections
import sys,codecs, os 
import operator
sys.stdout = codecs.getwriter('utf8')(sys.stdout)
from collections import defaultdict as dd

showsentcgi = "show-sent.cgi"

form = cgi.FieldStorage()
corpus = form.getfirst("corpus", "cmn")
sid = int(form.getfirst("sid", 1))
window = int(form.getfirst("window", 5))
if window > 200:
    window = 200
lemma = form.getfirst("lemma", "")
lemma = lemma.strip().decode('utf-8')

corpus2 = 'eng'
linkdb = 'cmn-eng'

con = sqlite3.connect("../db/%s.db" % corpus)
c = con.cursor()
##
## get monolingual stuff
##

ss = dd(lambda: dd(unicode))
c.execute("select sid, docID, sent from sent where sid >= ? and sid <= ?", 
          (sid - window, sid + window))
sss =set() ### all the synsets
for (s, d, sent) in c:
    sss.add(s)
    if lemma:
        for l in lemma.split():
            sent=sent.replace(l,"<font color='green'>%s</font>" % l)
    ss[d][s]=sent

query="""select corpusID, docid, doc, title, url from doc  
        where docid in (%s)""" % ','.join('?'*len(ss.keys()))
c.execute(query, ss.keys())

doc= dd(lambda: dd(list))
for (corpusID, docid, docname, title, url) in c:
    if url:
        if not url.startswith('http://'):
            url = 'http://' +url
    else:
        url=''
    doc[int(corpusID)][int(docid)] = (url, title, docname)

query="""select corpusID, corpus, title from corpus 
         where corpusID in (%s)""" % ','.join('?'*len(doc.keys()))
c.execute(query, doc.keys())

corp = dd(list)
for (corpusID, corpus, title) in c:
    #print corpusID, corpus, title
    corp[int(corpusID)]=(title, corpus)

###
### get links  ### FIXME -- how to tell which direction programatically?
###
links = dd(set)
ttt = dict()
if os.path.isfile("../db/%s.db" % linkdb):
    lcon = sqlite3.connect("../db/%s.db" % linkdb)
    lc = lcon.cursor() 
    query="""select fsid, tsid from slink  
        where fsid in (%s)""" % ','.join('?'*len(sss))
    lc.execute(query, list(sss))
    for (fsid, tsid) in lc:
        links[int(fsid)].add(int(tsid))
        ttt[tsid]=''
##
## Get translations
##
if os.path.isfile("../db/%s.db" % corpus2):
    tcon = sqlite3.connect("../db/%s.db" % corpus2)
    tc = tcon.cursor()
    query="""select sid, sent from sent
        where sid in (%s)""" % ','.join('?'*len(ttt.keys()))
    tc.execute(query, ttt.keys())
    for (sd, sent) in tc:
        ttt[sd]=sent


# 2014-07-14 [Tuan Anh]
# Add jQuery support & alternate sentence colors
print u"""Content-type: text/html; charset=utf-8\n
<html>
 <head>
   <meta http-equiv='Content-Type' content='text/html; charset=utf-8'>
   <meta http-equiv='content-language' content='zh'>
   <title>%s: %s ± %s</title>
   <script src='../jquery.js' language='javascript'></script>
   <script src='../js/show-sent.js' language='javascript'></script>
   <script>
      $( document ).ready(page_init);
   </script>
</head>""" % (corpus, sid, window)

print """<body>"""

# 2014-07-14 [Tuan Anh]
# Show/hide translation



for c in sorted(corp.keys()):
    print u"<h2>%s (%s)</h2>" % corp[c]
    print "<div><button  style='float:right;' type='button' id='btnTran' name='btnTran'>Toggle Translation</button></div>"
    for d in sorted(doc[c].keys()):
        print u"<h3><a href='%s'>%s (%s)</a></h3>" % doc[c][d]
        print "<p>" 
        roll_color_alt = ['#ffffff', '#fafafa']
        roll_color = 0
        for s in sorted(ss[d].keys()):
            roll_color = 0 if roll_color == 1 else 1
            print "<div style='background-color: %s'>" % roll_color_alt[roll_color]
            if s ==sid:
                print "<span style='color:red'>%d</span>&nbsp;&nbsp;&nbsp;&nbsp;%s" % (s, 
                                                                            ss[d][s])
            else:
                print "%s&nbsp;&nbsp;&nbsp;&nbsp;%s" % (s, ss[d][s])
            for t in links[s]:
                print "<br/><font color='#505050' class='trans'>%s&nbsp;&nbsp;&nbsp;&nbsp;%s</font>" % (t, 
                                                                                      ttt[t]) 
            print "</div>"

print """</body></html>"""
