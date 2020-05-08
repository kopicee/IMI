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
#import cgitb; cgitb.enable()  # for troubleshooting
import codecs
from collections import defaultdict as dd
import os
import sys

import sqlite3


def placeholders_for(iterable, symbol='?'):
    """Make SQLite placeholders for data; [1, 2, 3] -> '?,?,?'"""
    return ','.join(symbol for x in iterable)


# sys.stdout = codecs.getwriter('utf8')(sys.stdout)

showsentcgi = "show-sent.cgi"

form = cgi.FieldStorage()

# Corpus to connect to:
corpus = form.getfirst("corpus", "cmn")

# Sentence ID to look up
target_sid = int(form.getfirst("sid", 101510))

# Number of sentences preceding and following target_sid to show for context
window = int(form.getfirst("window", 5))
if window > 200:
    window = 200

# Space-delimited string of lemmas to highlight
lemma = form.getfirst("lemma", "车")
#lemma = codecs.encode(lemma.strip(), 'utf8')
lemma = lemma.strip()

# Databases to fetch aligned translated sentences from
linkdb = 'cmn-eng'  # 1:1 linked sentenceids from Mandarin to English
corpus2 = 'eng'  # English db to fetch linked sentenceids

###
### Get monolingual stuff
###
# (Wilson) ss: a dict of sentences {docID: {sentenceID: sentence}}
# (Wilson) sss: a set of all sentence IDs
ss = dd(lambda: dd(str))
sss = set() ### all the synsets

# FIXME(Wilson): Constrain instead of letting user specify filename to connect
con = sqlite3.connect("../db/%s.db" % corpus)
c = con.cursor()

c.execute('SELECT sid, docID, sent FROM sent WHERE sid >= ? AND sid <= ?',
          (target_sid - window, target_sid + window))
for (sid, docid, sent) in c:
    sss.add(sid)
    ss[docid][sid] = sent

# (Wilson) Extract documents containing those sentences into dict of
#   doc = {corpusID: docID: (url, title, docname)}
query = """SELECT corpusID, docid, doc, title, url
           FROM doc
           WHERE docid IN (%s)""" % placeholders_for(ss)
c.execute(query, list(ss.keys()))

doc = dd(lambda: dd(tuple))
for (corpusID, docid, docname, title, url) in c:
    corpusID, docid = int(corpusID), int(docid)
    if url:
        if not url.startswith('http://') or url.startswith('https://'):
            url = 'http://' + url
    else:
        url = ''
    doc[corpusID][docid] = (url, title, docname)

# (Wilson) Extract subcorpora containing those documents into dict of
#   corp = {corpusID: (title, corpusName)}
query = """SELECT corpusID, corpus, title
           FROM corpus
           WHERE corpusID in (%s)""" % placeholders_for(doc)
c.execute(query, list(doc.keys()))

corp = dd(tuple)
for (corpusID, corpus, title) in c:
    corp[int(corpusID)] = (title, corpus)

### (Wilson) Extract translations.
### First, fetch sentenceids in the target lang (tsids) linked/aligned to the
### source sentenceids of interest (fsids). Next, querying the target lang's db
### to resolve tsids -> sentences
##
## get links from fsids to tsids  ### FIXME -- how to tell which direction programatically?
##
links = dd(set)  # {fsid: set(tsids...)}
ttt = dd(str)  # {tsid: tgtSentence}

if os.path.isfile("../db/%s.db" % linkdb):
    lcon = sqlite3.connect("../db/%s.db" % linkdb)
    lc = lcon.cursor()

    # (Wilson) fsid, tsid means from/to sid... I think
    query = """SELECT fsid, tsid
               FROM slink
               WHERE fsid IN (%s)""" % placeholders_for(sss)
    lc.execute(query, list(sss))

    for (fsid, tsid) in lc:
        fsid, tsid = int(fsid), int(tsid)
        links[fsid].add(tsid)
        ttt[tsid] = ''

##
## Get translations from tsids
##
if os.path.isfile("../db/%s.db" % corpus2):
    tcon = sqlite3.connect("../db/%s.db" % corpus2)
    tc = tcon.cursor()
    query = """SELECT sid, sent
               FROM sent
               WHERE sid IN (%s)""" % placeholders_for(ttt)
    tc.execute(query, list(ttt.keys()))
    for (tsid, sent) in tc:
        ttt[tsid] = sent


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
PER_CORPUS = """
  <h2>{c_title} ({c_name})</h2>
  <div>
    <button style="float:right;" type="button" id="btnTran" name="btnTran">
      Toggle Translation
    </button>
  </div>
"""

PER_DOCUMENT = """
  <h3><a href="{d_url}">{d_title} ({d_name})</a></h3>
  <p>
"""

PER_SENTENCE = """
  <div style="background-color: {row_bgcol}">
    <span{highlight}>{sid}</span>
    &nbsp;&nbsp;&nbsp;&nbsp;{sent}
    {translations}
  </div>
"""

PER_TRANSLATION = """
    <br/>
    <font color="#505050" class="trans">
      {t_sid}&nbsp;&nbsp;&nbsp;&nbsp;{translated}
    </font>
"""

for corpid in sorted(corp.keys()):
    # Print header for each corpus in query result
    c_title, c_name = corp[corpid]
    print(PER_CORPUS.format(c_title=c_title, c_name=c_name))

    documents = doc[corpid]

    for docid in sorted(documents.keys()):
        # Print header for each document
        d_url, d_title, d_name = documents[docid]
        print(PER_DOCUMENT.format(d_url=d_url, d_title=d_title, d_name=d_name))

        # Print sentences from each document
        sentences = ss[docid]
        row_bgcols = ['#ffffff', '#fafafa']
        for i, sid in enumerate(sorted(sentences.keys())):
            sent = sentences[sid]

            # Highlight lemmas if any were specified by user
            if lemma:
                for lem in lemma.split():
                    hilite = f'<span style="background: lightgreen">{lem}</span>'
                    sent = sent.replace(lem, hilite)

            # Highlight sentence if sentence id was specified by user
            highlight = ' style="color:red"' if sid == target_sid else ''

            # Background colour of the row; modulo works for any list length
            row_bgcol = row_bgcols[i % len(row_bgcols)]

            translations = ''.join(
                PER_TRANSLATION.format(t_sid=t_sid, translated=ttt[t_sid])
                for t_sid in links[sid]
            )

            print(PER_SENTENCE.format(row_bgcol=row_bgcol,
                                      highlight=highlight,
                                      sid=sid,
                                      sent=sent,
                                      translations=translations))

print("""
  </body>
</html>
""")


# FIXME(Wilson): Close i/o and connections?
