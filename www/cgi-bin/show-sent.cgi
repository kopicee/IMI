#!/usr/bin/python
# -*- coding: utf-8 -*-
###
### This is a simple cgi-script for showing sentences in the corpus
###
### Copyright Francis Bond 2014 <bond@ieee.org>
### This is released under the CC BY license
### (http://creativecommons.org/licenses/by/3.0/)
### bugfixes and enhancements gratefuly received
import cgi
#import cgitb; cgitb.enable()  # for troubleshooting
import codecs
from collections import defaultdict as dd
import os
import sys

import sqlite3

# sys.stdout = codecs.getwriter('utf8')(sys.stdout)

showsentcgi = "show-sent.cgi"

form = cgi.FieldStorage()
corpus = form.getfirst("corpus", "cmn")
target_sid = int(form.getfirst("sid", 1))
window = int(form.getfirst("window", 5))
if window > 200:
    window = 200
lemma = form.getfirst("lemma", "")  # Space-delimited string of lemmas to highlight
lemma = codecs.encode(lemma.strip(), 'utf8')

corpus2 = 'eng'
linkdb = 'cmn-eng'

con = sqlite3.connect("../db/%s.db" % corpus)
c = con.cursor()
##
## Get monolingual stuff
##

# Extract all sentences from db into dict of {docID: {sid: sent}}
# (Wilson) ss: a dict of sentences indexed by [docID][sentenceID]
# (Wilson) sss: a set of all sentence IDs
ss = dd(lambda: dd(str))
sss = set() ### all the synsets
c.execute('SELECT sid, docID, sent FROM sent WHERE sid >= ? AND sid <= ?',
          (target_sid - window, target_sid + window))
for (sid, docid, sent) in c:
    sss.add(sid)
    if lemma:
        for lem in lemma.split():
            sent = sent.replace(lem, '<font color="green">%s</font>' % lem)
    ss[docid][sid] = sent

# (Wilson) Extract documents containing those sentences into dict of
#   {corpusID: docID: (url, title, docname)}
query = """SELECT corpusID, docid, doc, title, url
           FROM doc
           WHERE docid IN (%s)""" % ','.join('?' for docid in ss.keys())
c.execute(query, list(ss.keys()))

doc = dd(lambda: dd(tuple))
for (corpusID, docid, docname, title, url) in c:
    corpusID, docid = int(corpusID), int(docid)
    if url:
        if not url.startswith('http://'):
            url = 'http://' + url
    else:
        url = ''
    doc[corpusID][docid] = (url, title, docname)

# (Wilson) Extract subcorpora containing those documents into dict of
#   {corpusID: (title, corpusName)}
query = """SELECT corpusID, corpus, title
           FROM corpus
           WHERE corpusID in (%s)""" % ','.join('?' for corpusID in doc.keys())
c.execute(query, list(doc.keys()))
corp = dd(list)
for (corpusID, corpus, title) in c:
    corp[int(corpusID)] = (title, corpus)

###
### get links  ### FIXME -- how to tell which direction programatically?
###
links = dd(set)
ttt = dict()
if os.path.isfile("../db/%s.db" % linkdb):
    lcon = sqlite3.connect("../db/%s.db" % linkdb)
    lc = lcon.cursor()
    # (Wilson) fsid, tsid means from/to sid... I think
    query = """SELECT fsid, tsid 
               FROM slink
               WHERE fsid IN (%s)""" % ','.join('?' for sid in sss)
    lc.execute(query, list(sss))
    for (fsid, tsid) in lc:
        fsid, tsid = int(fsid), int(tsid)
        links[fsid].add(tsid)
        ttt[tsid] = ''
##
## Get translations
##
if os.path.isfile("../db/%s.db" % corpus2):
    tcon = sqlite3.connect("../db/%s.db" % corpus2)
    tc = tcon.cursor()
    query = """SELECT sid, sent 
               FROM sent
               WHERE sid IN (%s)""" % ','.join('?' for tsid in ttt)
    tc.execute(query, list(ttt.keys()))
    for (sid, sent) in tc:
        ttt[sid] = sent


# 2014-07-14 [Tuan Anh]
# Add jQuery support & alternate sentence colors
# FIXME(Wilson) According to MDN, using <meta http-equiv="content-language">
#   is considered Bad Practice. Should we switch to <html lang="foo">?
# https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Content-Language
print('Content-type: text/html; charset=utf-8')
print()
print("""
<html>
  <head>
    <meta http-equiv="Content-Type" content="text/html; charset=utf-8">
    <meta http-equiv="content-language" content="zh">
    <title>{corpus_name}: {sid} ± {window}</title>
    <script src="../jquery.js" language="javascript"></script>
    <script src="../js/show-sent.js" language="javascript"></script>
    <script>
      $( document ).ready(page_init);
    </script>
  </head>
  <body>
""".format(
    corpus_name=corpus,
    sid=target_sid,
    window=window
))


# 2014-07-14 [Tuan Anh]
# Show/hide translation
per_corpus = """
  <h2>{c_title} ({c_name})</h2>
  <div>
    <button style="float:right;" type="button" id="btnTran" name="btnTran">
      Toggle Translation
    </button>
  </div>
"""

per_document = """
  <h3><a href="{d_url}">{d_title} ({d_name})</a></h3>
  <p>
"""

per_sentence = """
  <div style="background-color: {row_col}">
    <span{highlight}>{sid}</span>
    &nbsp;&nbsp;&nbsp;&nbsp;{sent}
    {translations}
  </div>
"""

per_translation = """
    <br/>
    <font color="#505050" class="trans">
      {t_sid}&nbsp;&nbsp;&nbsp;&nbsp;{translated}
    </font>
"""

for corpid in sorted(corp.keys()):
    c_title, c_name = corp[corpid]
    print(per_corpus.format(**locals()))

    documents = doc[corpid]
    sentences = ss[corpid]

    for docid in sorted(doc[corpid].keys()):
        d_url, d_title, d_name = doc[corpid][docid]
        print(per_document.format(**locals()))

        row_cols = ['#ffffff', '#fafafa']
        for i, sid in enumerate(sorted(ss[docid].keys())):
            sent = ss[docid][sid]

            row_col = row_cols[i % len(row_cols)]
            highlight = ' style="color:red"' if sid == target_sid else ''

            translations = ''.join(
                per_translation.format(t_sid=t_sid, translated=ttt[t_sid])
                for t_sid in links[sid]
            )

            print(per_sentence.format(**locals()))

print("""
  </body>
</html>
""")
