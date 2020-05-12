#!/usr/bin/env python
# -*- coding: utf-8 -*-

# KNOWN BUGS:
######################################################################
# There seems to be a bug about ';' in the URI. 
# Our server is accepting any kind of punctuation but ';' or " ' "
# For now, I'm just printing nothing about these in wordviewmode.
######################################################################

"""
TODO:
- Strongly recommend a whitelist check for `searchlang` values since it's used 
  to match db files on disk and also goes into a <script> tag (super taboo!)
"""

import cgi, urllib
import cgitb; cgitb.enable()  # for troubleshooting
from os import environ  # for cookies
import re, sqlite3, collections
from collections import defaultdict, namedtuple, OrderedDict

import datetime
import sys, codecs

from ntumc_webkit import *
from lang_data_toolkit import *

sys.stdout = codecs.getwriter('utf8')(sys.stdout)
reload(sys)
sys.setdefaultencoding('utf8')


# create the error log for the cgi errors
errlog = codecs.open('cgi_err.log', 'w+', 'utf-8')
errlog.write("LAST SEARCH LOG:\n")


cginame = "NTU Multilingual Corpus Interface"
ver = "0.1"
url = "http://compling.hss.ntu.edu.sg/"


dd = defaultdict


def placeholders_for(iterable, symbol='?'):
    """Make SQLite placeholders for data; [1, 2, 3] -> '?,?,?'"""
    return ','.join(symbol for x in iterable)


form = cgi.FieldStorage()

mode = cgi.escape(form.getfirst('mode', ''))
postag = cgi.escape(form.getfirst('postag', '')) # FOR WORDVIEW
# wordtag = form.getlist("wordtag[]") # FOR WORDVIEW
wordtag = [cgi.escape(t) for t in form.getlist('wordtag[]')]
# wordclemma = form.getlist("wordclemma[]") # FOR WORDVIEW
wordclemma = [cgi.escape(c) for c in form.getlist('wordclemma[]')]

################################################################################
# LANGUAGE CHOICES: it allows the choice of a main
# search language, and as many other languages
# as wanted to show parallel alignment.
# The same language as the search language cannot
# be chosen as a "see also language"
################################################################################
searchlang = cgi.escape(form.getfirst('searchlang', 'eng'))
# langs2 = form.getlist("langs2")
langs2 = [cgi.escape(l) for l in form.getlist('langs2')]
if searchlang in langs2:
    langs2.remove(searchlang)


# senti = form.getlist("senti[]") # receives either 'mlsenticon', 'sentiwn', both or none! 
senti = [cgi.escape(s) for s in form.getlist('senti[]')]
if 'mlsenticon' in senti and 'sentiwn' in senti:
    senti = 'comp' # then it will compile both sentiment scores

concept = cgi.escape(form.getfirst('concept', '')) # receives a synset
ph_concept = concept or ''
clemma = cgi.escape(form.getfirst('clemma', '')) # receives a lemmatized concept 
ph_clemma = clemma or ''
word = cgi.escape(form.getfirst('word', '')) # receives a surface form
ph_word = word or ''
lemma = cgi.escape(form.getfirst('lemma', '')) # receives a lemmatized word
ph_lemma = lemma or ''
limit = cgi.escape(form.getfirst('limit', '10')) # limit number os sentences to show

sentlike = cgi.escape(form.getfirst('sentlike', '')) # try to match pattern to sentence (glob pattern)
ph_sentlike = sentlike or ''



#########################################
# SIDS FROM TO
sid_from = 0
sid_to = 1000000
try:
    sid_from = int(cgi.escape(form.getfirst('sid_from', 0)))
except:
    pass
try:
    sid_to = int(cgi.escape(form.getfirst('sid_to', 1000000)))
except:
    pass
##########################################

# pos_eng = form.getlist("selectpos-eng")
# pos_cmn = form.getlist("selectpos-cmn")
# pos_jpn = form.getlist("selectpos-jpn")
# pos_ind = form.getlist("selectpos-ind")
# pos_ita = form.getlist("selectpos-ita")

pos_form = dict()
for lang in 'eng cmn jpn ind ita'.split():
    formkey = f'selectpos-{lang}'
    pos_form[lang] = [cgi.escape(pos) for pos in form.getlist(formkey)]


# corpuslangs = ['eng', 'cmn', 'jpn', 'ind'] # THIS SHOULD GO TO DATA.py
corpusdb = "../db/%s.db" % searchlang



usr = cgi.escape(form.getfirst('usr', '')) # should be fetched by cookie!
userid = cgi.escape(form.getfirst('userid', 'all')) # defaults to every user
mode = cgi.escape(form.getfirst('mode','')) # viewing mode
source = cgi.escape(form.getfirst('source[]','')) # choose source, default is ntmuc


### reference to self (.cgi)
selfcgi = "showcorpus.cgi"

### working wordnet.db 
wndb = "../db/wn-ntumc.db"

### reference to wn-grid (search .cgi)
URL_WNCGI_LEMMA = "wn-gridx.cgi?gridmode=ntumc-noedit&lang=%s&lemma=" % searchlang
URL_WNCGI_SS = "wn-gridx.cgi?gridmode=ntumc-noedit&lang=%s&synset=" % searchlang


#############################
# SQLITE Query Preparation
#############################
searchquery = ""  # Human-friendly representation of query params
# searchquery += "(Language:%s)+" % searchlang

"""(Wilson)
Each _q var is a tuple of (sql_condition, value). 
searchquery is basically a human-friendly representation of the *_q vars.

We can unify these in a single struct with a QueryConstraint namedtuple with the
following fields:
  sql (str) - a constituent of the SQL WHERE clause
  value (list) - a list of values to be extended into the single list of args
                 passed into cursor.execute()
  hf (str) - Human-friendly representation of the constraint, usually formatted
             like "(Constraint-Name:value)"
"""
QueryConstraint = namedtuple('QueryConstraint', 'sql, value, hf')
UNCONSTRAINED = QueryConstraint(sql='', value=[], hf='')

### Init query params to null
# The generator compre yields tuples into the OrderedDict to ensure consistent 
# ordering for the human-friendly printout. As of Python 3.7 dict keys iterate 
# in order of insertion, but explicit is better than implicit.
CONSTRAINT_KEYS = [
    'sentlike', 'concept', 'clemma', 'word', 'lemma',  # simple AND =/GLOB
    'pos',  # pos IN ('spam', 'eggs', 'ham')
    'sid_from', 'sid_from2', 'sid_to', 'sid_to2',  # <= or >=
    'limit',  # LIMIT foo
]
query_constraints = OrderedDict((key, UNCONSTRAINED) for key in CONSTRAINT_KEYS)

### Parse form data into constraints in the query
if sentlike:
    query_constraints['sentlike'] = QueryConstraint(""" AND sent.sent GLOB ? """,
                                                    [sentlike],
                                                    f'(Sentence-Like:{sentlike})')

if concept:
    query_constraints['concept'] = QueryConstraint(""" AND tag = ? """,
                                                   [concept],
                                                   f'(Concept:{concept})')

if clemma:
    query_constraints['clemma'] = QueryConstraint(""" AND clemma GLOB ? """,
                                                  [clemma],
                                                  f'(C-Lemma:{clemma})')

if word:
    query_constraints['word'] = QueryConstraint(""" AND word GLOB ? """,
                                                [word],
                                                f'(Word:{word})')

if lemma:
    query_constraints['lemma'] = QueryConstraint(""" AND lemma GLOB ? """,
                                                 [lemma],
                                                 f'(Lemma:{lemma})')

if len(pos_form[searchlang]) > 0:
    pos_of_lang = pos_form[searchlang]

    quesmarks = placeholders_for(pos_of_lang)
    humanfriendly = ' or '.join(f"'{x}'" for x in pos_of_lang)

    query_constraints['pos'] = QueryConstraint(f""" AND pos in ({quesmarks}) """,
                                               pos_of_lang,
                                               f'(POS:{humanfriendly})')

if sid_from != 0:
    query_constraints['sid_from'] = QueryConstraint(f""" AND sent.sid >= ? """,
                                                    sid_from,
                                                    f'(SID>={sid_from})')
    query_constraints['sid_from2'] = QueryConstraint(f""" AND sid >= ? """,
                                                     sid_from,
                                                     hf=None)

if sid_to != 1000000:
    query_constraints['sid_to'] = QueryConstraint(f""" AND sent.sid <= ? """,
                                                  sid_to,
                                                  f'(SID<={sid_to})')
    query_constraints['sid_to2'] = QueryConstraint(f""" AND sid <= ? """,
                                                   sid_to,
                                                   hf=None)

release_match_style = False
if limit == 'all':
    # Limit explicitly uncapped
    query_constraints['limit'] = UNCONSTRAINED

else:
    sid_constraints = sid_from != 0 or sid_to != 1000000
    other_constraints = [query_constraints[key] != UNCONSTRAINED
                         for key in 'concept  clemma  word  lemma  pos'.split()]

    
    # If only constrained by sentenceIDs, cap the 'window size'
    if sid_constraints and not any(other_constraints):
        query_constraints['limit'] = QueryConstraint(f""" LIMIT ? """,
                                                     [5000],  # HARD CODED LIMIT 500 words
                                                     None)
        release_match_style = True
    
    # Otherwise cap by the given limit
    else:
        query_constraints['limit'] = QueryConstraint(f""" LIMIT ? """,
                                                    [limit],
                                                    None)
    
if mode == "wordview":
    # errlog.write("It entered wordview mode!<br>")

    ###########################
    # Connect to wordnet.db
    ###########################
    con = sqlite3.connect(wndb)
    wn = con.cursor()
    
    fetch_ss_name_def = """
        SELECT s.synset, name, src, lang, def, sid
        FROM (SELECT synset, name, src
              FROM synset
              WHERE synset in ({quesmarks})) s
        LEFT JOIN synset_def
        WHERE synset_def.synset = s.synset
        AND synset_def.lang in (?, 'eng')
    """.format(quesmarks=placeholders_for(wordtag))
    
    wn.execute(fetch_ss_name_def, wordtag + [searchlang])
    rows = wn.fetchall()
    
    ss_defs = dd(lambda: dd(lambda: dd(str)))
    ss_names = dd(lambda: dd(list))
    for synset, name, src, lang, ss_def, sid in rows:
        ss_names[synset] = [name, src]
        ss_defs[synset][lang][sid] = ss_def
    
    try:
        html_word = cgi.escape(word, quote=True)
    except:
        html_word = '' # The forms fails to read ; as the argument for word!
    try:
        html_lemma = cgi.escape(lemma, quote=True)
    except:
        html_lemma = '' # The forms fails to read ; as the argument for lemma!
    html_pos = cgi.escape(postag, quote=True)

    html_lemma_href = """<a class="fancybox fancybox.iframe" 
                          href="{endpoint}{arg}">{lemma}</a>
                      """.format(endpoint=URL_WNCGI_LEMMA,
                                 arg=html_lemma,
                                 lemma=html_lemma)
    
    html_postag_def = """<span title="{engdef}">{langdef}</span>
                      """.format(engdef=pos_tags[searchlang][postag]['eng_def'], 
                                 langdef=pos_tags[searchlang][postag]['def'])

    print(f"""Content-type: text/html; charset=utf-8\n
    <!DOCTYPE html>
    <html>
      <head>
        <meta http-equiv="Content-Type" content="text/html; charset=utf-8">
        <link href="../tag-wn.css" rel="stylesheet" type="text/css">
        <script src="../tag-wn.js" language="javascript"></script>
        <!-- KICKSTART -->
        <script src="../HTML-KickStart-master/js/kickstart.js"></script> 
        <link rel="stylesheet" media="all"
              href="../HTML-KickStart-master/css/kickstart.css"/>
        <title>{cginame}</title></head><body>
      </head>
      <body>
        <h6>Word Details</h6>
        <table>
          <tr><td>Word:</td><td>{html_word}</td></tr>
          <tr><td>POS:</td><td>{html_pos} ({html_postag_def})</td></tr>
          <tr><td>Lemma:</td><td>{html_lemma_href}</td></tr>
          <tr><td>Concept(s):</td><td>
    """)
    
    for i, tag in enumerate(wordtag):
        tag_defs = ""
        tag_defs += '; '.join(ss_defs[tag][searchlang].values())

        if searchlang != 'eng':
            if tag_defs:
                tag_defs += '<br>'
            tag_defs += '; '.join(ss_defs[tag]['eng'].values())

        if tag_defs == '':
            tag_defs = 'no_definition'
        
        try:
            concept_name = wordclemma[i]
        except:
            if tag in 'e  None  x  w  loc  org  per  dat  oth'.split():
                concept_name = tag
            else:
                concept_name = ss_names[tag][0]
        
        print(f"""
            <a class='fancybox fancybox.iframe'
               href='{URL_WNCGI_SS}{tag}'>{concept_name}</a> ({tag_defs})<br/>""")

    print("""
          </td></tr>
        </table>
      </body>
    </html>""")
    sys.exit(0)




# errlog.write("It did not enter wordviewmode!<br>")
# message = "" #TEST
###########################
# Connect to corpus.db
###########################
if corpusdb != "../db/None.db":
    conc = sqlite3.connect(corpusdb)
    cc = conc.cursor()
    cc2 = conc.cursor()


    ############################################################
    # If nothing is linked to a concept, then the query
    # should not have cwl (because that restricts the 
    # query to ONLY things that have concepts!
    ############################################################
    if concept_q != UNCONSTRAINED or clemma_q != UNCONSTRAINED:

        # errlog.write("It entered concept_q nor clemma_q =! EMPTY <br>")

        # showcorpus  ="""
        #    SELECT cl.sid, cl.cid, cl.tag 
        #    FROM (SELECT c.sid, c.cid, wid, tag 
        #          FROM (SELECT sid, cid, tag 
        #                FROM concept WHERE 1 > 0 {} {} {} {} ) c 
        #          LEFT JOIN cwl 
        #          WHERE cwl.sid = c.sid 
        #          AND c.cid = cwl.cid) cl 
        #    LEFT JOIN word 
        #    WHERE word.sid = cl.sid 
        #    AND word.wid = cl.wid {} {} {} {} 
        #    """.format(concept_q, clemma_q, sid_from_q2, 
        #               sid_to_q2, word_q, lemma_q, pos_q, limit_q)

        showcorpus_keys = """concept  clemma  sid_from  sid_to
                             word  lemma  pos  limit""".split()
        showcorpus_wheres = [query_constraints[key].sql
                             for key in showcorpus_keys]
        showcorpus = """
            SELECT cl.sid, cl.cid, cl.tag 
            FROM (SELECT c.sid, c.cid, wid, tag 
                  FROM (SELECT sid, cid, tag 
                        FROM concept WHERE 1 > 0 {} {} {} {} ) c 
                  LEFT JOIN cwl 
                  WHERE cwl.sid = c.sid 
                  AND c.cid = cwl.cid) cl 
            LEFT JOIN word 
            WHERE word.sid = cl.sid 
            AND word.wid = cl.wid {} {} {} {} 
        """.format(*showcorpus_wheres)

        # errlog.write("concept(tag): %s\n" % concept_q)
        # errlog.write("conceptlemma: %s\n" % clemma_q)
        # errlog.write("It will try to run the following query: <br>")
        # errlog.write("%s <br>" % showcorpus)
        # errlog.flush()

        showcorpus_params = []
        for key in showcorpus_keys:
            constr = query_constraints[key]
            if constr != UNCONSTRAINED:
                showcorpus_params += constr.value

        cc.execute(showcorpus, showcorpus_params)
        rows = cc.fetchall()

        sid_cid = dd(lambda: dd(list))
        for sid, cid, tag in rows:
            sid_cid[sid][cid] = [tag]
        
        sids = ','.join(f"'{sid}'" for sid in sid_cid.keys())
        # errlog.write("Executed ok and now has a list of sids: <br>")
        # errlog.write(" %s <br>" % str(sids))



    elif any(query_constraints[key] != UNCONSTRAINED
             for key in 'word  lemma  pos  sid_from  sid_to  sentlike'.split()):

        # errlog.write("The search was not related to concepts... <br>")

        # showcorpus = """
        # SELECT word.sid, word.wid
        # FROM word
        # LEFT JOIN sent
        # WHERE word.sid = sent.sid
        # %s %s %s %s %s %s %s""" % (word_q, lemma_q, pos_q, 
        #                            sid_from_q, sid_to_q, sentlike_q, limit_q)

        showcorpus_keys = """word  lemma  pos  sid_from  sid_to
                             sentlike  limit""".split()
        showcorpus_wheres = [query_constraints[key].sql
                             for key in showcorpus_keys]
        showcorpus = """
            SELECT word.sid, word.wid
            FROM word
            LEFT JOIN sent
            WHERE word.sid = sent.sid {} {} {} {} {} {} {}
        """.format(*showcorpus_wheres)

        # errlog.write("It will try to run the following query:\n")
        errlog.write('%s\n' % showcorpus)

        showcorpus_params = []
        for key in showcorpus_keys:
            constr = query_constraints[key]
            if constr != UNCONSTRAINED:
                showcorpus_params += constr.value

        cc.execute(showcorpus, showcorpus_params)


        rows = cc.fetchall()

        sid_cid = dd(lambda: dd(list))
        sid_matched_wid = dd(list)
        for sid, wid in rows:
            sid_matched_wid[sid].append(wid)
        sids = ','.join(f"'{sid}'" for sid in sid_matched_wid)

    else:
        #(Wilson) What???
        sids = ','.join("'%s'" % s for s in [])
    #######################################################################
    # THE sids HAS THE SIDS TO BE PRINTED IN AN SQLITE QUERY;  
    # IF CONCEPTS WERE SEARCHED, THEN THE DICT sid_cid HOLDS THAT INFO TOO
    #######################################################################


    sid_wid = dd(lambda: dd(list))
    fetch_sent = f"""
        SELECT sid, wid, word, lemma, pos
        FROM word
        WHERE sid in ({sids})
    """
    cc.execute(fetch_sent)
    rows = cc.fetchall()
    for sid, wid, word, lemma, pos in rows:
        pos = "unk" if pos == None else pos
        sid_wid[sid][wid] = [word, lemma, pos]

    #######################################################################
    # THE DICT sid_wid HAS THE FULL LIST OF SIDS BY WIDS;  
    #######################################################################

    fetch_sent_full_details = f"""
        SELECT w.sid, w.wid, w.word, w.lemma, w.pos, cwl.cid
        FROM (SELECT sid, wid, word, lemma, pos
              FROM word
              WHERE sid in ({sids}) ) w
        LEFT JOIN cwl
        WHERE w.wid = cwl.wid
        AND w.sid = cwl.sid
        ORDER BY w.sid
    """

    fetch_concept_details = f"""
        SELECT sid, cid, clemma, tag 
        FROM concept
        WHERE sid in ({sids})
        ORDER BY sid
    """

    sid_cid_wid = dd(lambda: dd(list))
    sid_wid_cid = dd(lambda: dd(list))
    sid_wid_tag = dd(lambda: dd(list))
    sid_cid_tag = dd(lambda: dd(str))
    sid_cid_clemma = dd(lambda: dd(str))

    sss = set() # holds the list of all tags (for sentiment)

    cc2.execute(fetch_concept_details)
    rows2 = cc2.fetchall()
    for sid, cid, clemma, tag in rows2:
        sid_cid_tag[sid][cid] = tag
        sid_cid_clemma[sid][cid] = clemma
        sss.add(tag)

    cc.execute(fetch_sent_full_details)
    rows = cc.fetchall()

    for sid, wid, word, lemma, pos, cid in rows:
        # TRY TO USE ONLY THE SECOND DICT
        # (IS IT COMPATIBLE WITH BOTH CASES?) 
        sid_cid_wid[sid][cid].append(wid)  # THIS IS TO COLOR EVERY WID IN CID
        sid_wid_cid[sid][wid].append(cid)
        sid_wid_tag[sid][wid].append(sid_cid_tag[sid][cid])

    conc.close()


    #######################################################################
    # THE DICT sid_cid_wid IDENTIFIES IF A WID BELONGS TO A CID IN SID
    # THE DICT sid_cid_tag HAS THE TAG FOR EACH CONCEPT IN SID
    # THE DICT sid_cid_clemma HAS THE C-LEMMA FOR EACH CONCEPT IN SID
    #######################################################################


    if langs2: # there may be more than 1 lang2, these dicts keep all the info

        # links[lang][fsid] = set(tsid)
        links = dd(lambda: dd(set)) # this holds the sid links between langs
        # l_sid_fullsent = {lang2: {sid: full_sentence} }
        l_sid_fullsent = dd(lambda: dd(str))

        l_sid_wid = dd(lambda: dd(lambda: dd(list)))
        l_sid_cid_wid = dd(lambda: dd(lambda: dd(list)))
        l_sid_wid_cid = dd(lambda: dd(lambda: dd(list)))
        l_sid_wid_tag = dd(lambda: dd(lambda: dd(list)))
        
        l_sid_cid_tag = dd(lambda: dd(lambda: dd(str)))
        l_sid_cid_clemma = dd(lambda: dd(lambda: dd(str)))

        errlog.write("There were langs2: %s \n" % ' | '.join(langs2)) #LOG

        # try to find a link database between searchlang and lang2
        for lang2 in langs2:
            lang2_sids = set()
            # FIXME(Wilson): Check for whitelist values instead of giving user
            #   control over which filename to connect
            dbfile = "../db/%s-%s.db" % (searchlang, lang2)
            revlink = 0

            if not os.path.isfile(dbfile):
                revdbfile = "../db/%s-%s.db" % (lang2, searchlang)
                if os.path.isfile(revdbfile):
                    dbfile = revdbfile
                    revlink = 1

            errlog.write("Found {}: {} \n".format(
                ['lang1-lang2', 'lang2-lang1'][revlink],
                linkdb)) #LOG

            lcon = sqlite3.connect("%s" % linkdb)
            lc = lcon.cursor()
            query = """SELECT fsid, tsid 
                       FROM slink 
                       WHERE {} in ({})""".format(['fsid', 'tsid'][revlink],
                                                  sids)
            lc.execute(query)
            
            for (fsid, tsid) in lc:
                if revlink:
                    fsid, tsid = tsid, fsid
                links[lang2][int(fsid)].add(int(tsid))
                lang2_sids.add(tsid) # this is a set of sids in the target langauge to fetch details

            lang2_sids = ','.join(f"'{s}'" for s in lang2_sids)
            errlog.write('Fetched sids: %s \n' % lang2_sids) #LOG
            errlog.write('links_dict: %s \n' % '|'.join(links.keys())) #LOG


            ##############################################
            # THIS IS TO GET THE LINKED LANGUAGES INFO
            # this will happen per lang in langs2.
            ##############################################

            corpusdb = "../db/%s.db" % lang2
            conc = sqlite3.connect(corpusdb)
            cc = conc.cursor()
            cc2 = conc.cursor()


            # STORE THE FULL SENTENCE, IN CASE THE LANG2 DOES NOT 
            # HAVE WORDS TO PRODUCE THE SENTENCE FROM...
            fetch_fullsent = """
                SELECT sid, sent.sent
                FROM sent
                WHERE sid in (%s)""" % lang2_sids
            cc.execute(fetch_fullsent)
            rows = cc.fetchall()
            for s, fullsent in rows:
                l_sid_fullsent[lang2][s] = fullsent
            ######################################################


            fetch_sent = """
                SELECT sid, wid, word, lemma, pos
                FROM word
                WHERE sid in (%s)""" % lang2_sids
            cc.execute(fetch_sent)
            rows = cc.fetchall()
            for sid, wid, word, lemma, pos in rows:
                pos = "unk" if pos == None else pos
                l_sid_wid[lang2][sid][wid] = [word, lemma, pos]


            fetch_sent_full_details = """
                SELECT w.sid, w.wid, w.word, w.lemma, w.pos, cwl.cid
                FROM (SELECT sid, wid, word, lemma, pos
                      FROM word
                      WHERE sid in (%s) ) w
                LEFT JOIN cwl
                WHERE w.wid = cwl.wid
                AND w.sid = cwl.sid
                ORDER BY w.sid""" % lang2_sids

            fetch_concept_details = """
                SELECT sid, cid, clemma, tag 
                FROM concept
                WHERE sid in (%s)
                ORDER BY sid""" % lang2_sids


            cc2.execute(fetch_concept_details)
            rows2 = cc2.fetchall()
            for sid, cid, clemma, tag in rows2:
                l_sid_cid_tag[lang2][sid][cid] = tag
                l_sid_cid_clemma[lang2][sid][cid] = clemma
                sss.add(tag) # add also synsets for other languages

            cc.execute(fetch_sent_full_details)
            rows = cc.fetchall()

            for sid, wid, word, lemma, pos, cid in rows:
                l_sid_cid_wid[lang2][sid][cid].append(wid)
                l_sid_wid_cid[lang2][sid][wid].append(cid)
                l_sid_wid_tag[lang2][sid][wid].append(l_sid_cid_tag[lang2][sid][cid])

            conc.close()

    sss = ",".join("'%s'" % s for s in sss) # sqlite ready list of all synsets
    if senti in ['comp',['sentiwn'],['mlsenticon']]:
        
        #NEED TO OVERWRITE WN PATH (wn-ntumc.db) does not have sentiment
        wndb = "../../omw/wn-multix.db"

        ss_resource_sent = dd(lambda: dd(lambda: dd(float)))
        ###########################
        # Connect to wordnet.db
        ###########################
        con = sqlite3.connect(wndb)
        wn = con.cursor()
        #(Wilson) I think misc is the reliability score
        ss_resource_sentiment = """
            SELECT synset, resource, xref, misc
            FROM xlink
            WHERE resource in ('MLSentiCon','SentiWN')
            AND synset in (%s)
        """ % (sss)
        
        wn.execute(ss_resource_sentiment)
        rows = wn.fetchall()

        for synset, resource, xref, misc in rows:
            ss_resource_sent[synset][resource][xref] = float(misc)
                

else:
    sid_cid = dd(lambda: dd(list))
    sid_wid = dd(lambda: dd(list))
    sid_cid_wid = dd(lambda: dd(list))
    sid_wid_cid = dd(lambda: dd(list))
    sid_cid_tag = dd(lambda: dd(str))
    sid_cid_clemma = dd(lambda: dd(str))
    sid_matched_wid = dd(list)


################################################################
# FETCH COOKIE
################################################################
# hashed_pw = ""
# if environ.has_key('HTTP_COOKIE'):
#    for cookie in environ['HTTP_COOKIE'].split(';'):
#       (key, value ) = cookie.strip().split('=');
#       if key == "UserID":
#          usr = value
#       if key == "Password":
#          hashed_pw = value

################################################################
# HTML
################################################################

### Header
print("""Content-type: text/html; charset=utf-8\n
<!DOCTYPE html>
<html>
  <head>
    <meta http-equiv="Content-Type" content="text/html; charset=utf-8">
    <link href="../tag-wn.css" rel="stylesheet" type="text/css">
    <script src="../tag-wn.js" language="javascript"></script>

    <!-- For DatePicker -->
    <link rel="stylesheet" href="//code.jquery.com/ui/1.11.2/themes/smoothness/jquery-ui.css">
    <script src="//code.jquery.com/jquery-1.10.2.js"></script>
    <script src="//code.jquery.com/ui/1.11.2/jquery-ui.js"></script>
    <script>
        $(function() {
          $( "#datefrom" ).datepicker();
          $( "#dateto" ).datepicker();
        });
    </script>

    <!-- FANCYBOX -->
    <!-- Needs JQuery -->
    <!-- Add FancyBox main JS and CSS files -->
    <script type="text/javascript" 
     src="../fancybox/source/jquery.fancybox.js?v=2.1.5"></script>
    <link rel="stylesheet" type="text/css" 
     href="../fancybox/source/jquery.fancybox.css?v=2.1.5" 
     media="screen" />
    <!-- Make FancyBox Ready on page load (adds Classes) -->
    <script type="text/javascript" 
     src="../fancybox-ready.js"></script>


    <!-- MULTIPLE SELECT -->
    <!-- Needs JQuery -->
    <!-- Add MultipleSelect main JS and CSS files -->
    <script type="text/javascript" 
     src="../multiple-select-master/jquery.multiple.select.js"></script>
    <link rel="stylesheet" type="text/css" 
     href="../multiple-select-master/multiple-select.css"/>
    <!-- Ready the function! -->
    <script>
        $('#selectpos').multipleSelect();
    </script> """),

# FIXME(Wilson): Definitely constrain searchlang! Allowing user input inside a
#   <script> tag is terrifying!
#   For now I will sanitize by removing non-alphanumeric characters
searchlang = ''.join(c for c in searchlang if c.isalnum())

print(""" \n <!-- TO SHOW POS DIVS IN A SELECT LANG OPTIONS-->
    <script>
        $(document).ready(function () {
          $('.defaulthide').hide();
          $('#pos-%s').show();
          $('#corpuslang').change(function () {
            $('.defaulthide').hide();
            $('#pos-'+$(this).val()).show();
          })
        });
    </script>""" % searchlang)

print("""<!-- TO SHOW / HIDE BY ID (FOR DIV)-->
    <script type="text/javascript">
        function toggle_visibility(id) {
            var e = document.getElementById(id);
            if (e.style.display == 'block') {
               e.style.display = 'none';
               e.style.visibility = 'collapse';
            } else {
               e.style.display = 'block';
               e.style.visibility = 'visible';
           }
        }
    </script>


    <!-- KICKSTART -->
    <script src="../HTML-KickStart-master/js/kickstart.js"></script> 
    <link rel="stylesheet" href="../HTML-KickStart-master/css/kickstart.css" media="all" />



    <style>
        mark { 
            background-color: #FFA6A6;
        }
        </style>
        <style>
          hr {
            padding: 0px;
            margin: 10px;    
          }
    </style>


    <!-- THIS IS A TRY OUT FOR A COOL CSS TOOLTIP! MUST USE class="tooltip-bottom" data-tooltip="I'm the tooltip data!" -->
    <style>
        /**
         * Tooltips!
         */

        /* Base styles for the element that has a tooltip */
        [data-tooltip],
        .tooltip {
          position: relative;
          cursor: pointer;
        }

        /* Base styles for the entire tooltip */
        [data-tooltip]:before,
        [data-tooltip]:after,
        .tooltip:before,
        .tooltip:after {
          position: absolute;
          visibility: hidden;
          -ms-filter: "progid:DXImageTransform.Microsoft.Alpha(Opacity=0)";
          filter: progid:DXImageTransform.Microsoft.Alpha(Opacity=0);
          opacity: 0;
          -webkit-transition: 
        	  opacity 0.2s ease-in-out,
        		visibility 0.2s ease-in-out,
        		-webkit-transform 0.2s cubic-bezier(0.71, 1.7, 0.77, 1.24);
        	-moz-transition:    
        		opacity 0.2s ease-in-out,
        		visibility 0.2s ease-in-out,
        		-moz-transform 0.2s cubic-bezier(0.71, 1.7, 0.77, 1.24);
        	transition:         
        		opacity 0.2s ease-in-out,
        		visibility 0.2s ease-in-out,
        		transform 0.2s cubic-bezier(0.71, 1.7, 0.77, 1.24);
          -webkit-transform: translate3d(0, 0, 0);
          -moz-transform:    translate3d(0, 0, 0);
          transform:         translate3d(0, 0, 0);
          pointer-events: none;
        }

        /* Show the entire tooltip on hover and focus */
        [data-tooltip]:hover:before,
        [data-tooltip]:hover:after,
        [data-tooltip]:focus:before,
        [data-tooltip]:focus:after,
        .tooltip:hover:before,
        .tooltip:hover:after,
        .tooltip:focus:before,
        .tooltip:focus:after {
          visibility: visible;
          -ms-filter: "progid:DXImageTransform.Microsoft.Alpha(Opacity=100)";
          filter: progid:DXImageTransform.Microsoft.Alpha(Opacity=100);
          opacity: 1;
        }

        /* Base styles for the tooltip's directional arrow */
        .tooltip:before,
        [data-tooltip]:before {
          z-index: 1001;
          border: 6px solid transparent;
          background: transparent;
          content: "";
        }

        /* Base styles for the tooltip's content area */
        .tooltip:after,
        [data-tooltip]:after {
          z-index: 1000;
          padding: 8px;
          width: 160px;
          background-color: #000;
          background-color: hsla(0, 0%, 20%, 0.9);
          color: #fff;
          content: attr(data-tooltip);
          font-size: 13px;
          line-height: 1.2;
        }

        /* Directions */

        /* Top (default) */
        [data-tooltip]:before,
        [data-tooltip]:after,
        .tooltip:before,
        .tooltip:after,
        .tooltip-top:before,
        .tooltip-top:after {
          bottom: 100%;
          left: 50%;
        }

        [data-tooltip]:before,
        .tooltip:before,
        .tooltip-top:before {
          margin-left: -6px;
          margin-bottom: -12px;
          border-top-color: #000;
          border-top-color: hsla(0, 0%, 20%, 0.9);
        }

        /* Horizontally align top/bottom tooltips */
        [data-tooltip]:after,
        .tooltip:after,
        .tooltip-top:after {
          margin-left: -80px;
        }

        [data-tooltip]:hover:before,
        [data-tooltip]:hover:after,
        [data-tooltip]:focus:before,
        [data-tooltip]:focus:after,
        .tooltip:hover:before,
        .tooltip:hover:after,
        .tooltip:focus:before,
        .tooltip:focus:after,
        .tooltip-top:hover:before,
        .tooltip-top:hover:after,
        .tooltip-top:focus:before,
        .tooltip-top:focus:after {
          -webkit-transform: translateY(-12px);
          -moz-transform:    translateY(-12px);
          transform:         translateY(-12px); 
        }

        /* Left */
        .tooltip-left:before,
        .tooltip-left:after {
          right: 100%;
          bottom: 50%;
          left: auto;
        }

        .tooltip-left:before {
          margin-left: 0;
          margin-right: -12px;
          margin-bottom: 0;
          border-top-color: transparent;
          border-left-color: #000;
          border-left-color: hsla(0, 0%, 20%, 0.9);
        }

        .tooltip-left:hover:before,
        .tooltip-left:hover:after,
        .tooltip-left:focus:before,
        .tooltip-left:focus:after {
          -webkit-transform: translateX(-12px);
          -moz-transform:    translateX(-12px);
          transform:         translateX(-12px); 
        }

        /* Bottom */
        .tooltip-bottom:before,
        .tooltip-bottom:after {
          top: 100%;
          bottom: auto;
          left: 50%;
        }

        .tooltip-bottom:before {
          margin-top: -12px;
          margin-bottom: 0;
          border-top-color: transparent;
          border-bottom-color: #000;
          border-bottom-color: hsla(0, 0%, 20%, 0.9);
        }

        .tooltip-bottom:hover:before,
        .tooltip-bottom:hover:after,
        .tooltip-bottom:focus:before,
        .tooltip-bottom:focus:after {
          -webkit-transform: translateY(12px);
          -moz-transform:    translateY(12px);
          transform:         translateY(12px); 
        }

        /* Right */
        .tooltip-right:before,
        .tooltip-right:after {
          bottom: 50%;
          left: 100%;
        }

        .tooltip-right:before {
          margin-bottom: 0;
          margin-left: -12px;
          border-top-color: transparent;
          border-right-color: #000;
          border-right-color: hsla(0, 0%, 20%, 0.9);
        }

        .tooltip-right:hover:before,
        .tooltip-right:hover:after,
        .tooltip-right:focus:before,
        .tooltip-right:focus:after {
          -webkit-transform: translateX(12px);
          -moz-transform:    translateX(12px);
          transform:         translateX(12px); 
        }

        /* Move directional arrows down a bit for left/right tooltips */
        .tooltip-left:before,
        .tooltip-right:before {
          top: 3px;
        }

        /* Vertically center tooltip content for left/right tooltips */
        .tooltip-left:after,
        .tooltip-right:after {
          margin-left: 0;
          margin-bottom: -16px;
        }
    </style>
    """)

if release_match_style:
    print("""
    <style> 
        .match {
          color: black;
          font-weight: normal;
          text-decoration: none;
        }
    </style>""")

print("""
    <title>%s</title>
 </head>
 <body>
 """ % cginame)

# print sss #TEST
# print "senti_value: " + str(senti) #TEST
# print ss_resource_sent #TEST
# try: #TEST
#     print links #TEST
# except: #TEST
#     print "something happened to the links dict" #TEST

try:
# if 1 > 0: #TEST
    # print cgi.escape(showcorpus, quote=True) #TEST
    # print langs2  #TEST
    # print lang2_sids  #TEST
    # print l_sid_fullsent['eng']
    # for lang in l_sid_fullsent.keys():
    #     print lang  
    #     for sid in l_sid_fullsent[lang]:
    #         print str(sid) 
    #         #+ ':' + l_sid_fullsent[lang][sid]
    # print fetch_fullsent #TEST
    # print searchlang #TEST
    # print searchlang in langs2 #TEST
    # print "<p><br><br><br><br><br>" # TEST
    # print "<br><br>" #TEST
    # print "sids: " + sids + "<br><br><br>" #TEST 
    # print sid_cid #TEST

    searchquery = '+'.join(query_constraints[key].hf
                       for key in sorted(CONSTRAINT_KEYS)
                       if query_constraints[key].hf)
    searchquery = cgi.escape(searchquery)
    if len(sids) == 0:
        print('<b>Results for: </b>')
        if searchquery == "":
            print('No query was made.')
        else:
            print(searchquery)
            
        print('<br>')
        print('<b>No results were found!</b>')

    # ALL THIS SHOULD BE: IF "CONCEPT" OR "C-LEMMA"
    # THEY SHOLD BE FILTERED BY TAG = x OR e
    # HERE WE'RE SHOWING BY EXISTING CONCEPTS
    elif (query_constraints['concept'] != UNCONSTRAINED
          or query_constraints['clemma'] != UNCONSTRAINED):
        
        count = 0
        # sid_cid is nested dict of {sid: {cid: [concept_tag ...]}}
        for sid, cid_dict in sid_cid.items():
            count += len(cid_dict)
        print(f'<b>{count} results for: </b>')
        print(searchquery)

        print("""<table class="striped tight">""")
        print("""<thead><tr><th>Sid</th><th>Sentence</th></tr></thead>""")

        ##################################################################
        # If there is more than one concept per sid match, we are
        # printing 2 copies of that sentence and showing the different
        # concepts highlighted!
        # We're also excluding by tag! (Don't show if tag = 'x' or 'e')
        ##################################################################
        for sid, cid_dict in sorted(sid_cid.items()):
            for cid, tag in sid_cid[sid].items():

                # sentiment = """<div style="height:0.5em; 
                # background: linear-gradient(to right"""

                print """<tr>"""
                print """<td><a class='largefancybox fancybox.iframe' 
                href='%s?corpus=%s&sid=%d&lemma=%s'>%s</a></td>
                """ % (showsentcgi, searchlang, sid, '', sid)

                s_string = ""
                for wid, wid_info in sorted(sid_wid[sid].items()):

                    ########################################################
                    # SENTIMENT
                    ########################################################
                    score = 0
                    MLSentiCon = 0
                    SentiWN = 0
                    if senti == 'comp':
                        for tag in sid_wid_tag[sid][wid]:
                            try:
                                MLSentiCon += (ss_resource_sent[tag]['MLSentiCon']['Positive'] + 
                                               -1*ss_resource_sent[tag]['MLSentiCon']['Negative'])
                            except:
                                # print "failed to add to MLSentiCon" #TEST
                                MLSentiCon += 0
                            try:
                                SentiWN += (ss_resource_sent[tag]['SentiWN']['Positive'] +
                                          -1*ss_resource_sent[tag]['SentiWN']['Negative'])
                            except:
                                # print "failed to add to SentiWN" #TEST
                                SentiWN += 0
                            score += (MLSentiCon + SentiWN)
                            
                        sentitooltip = """ MLSentiCon: %0.3f;  SentiWN: %0.3f; """ % (MLSentiCon, SentiWN)

                    elif senti == ['mlsenticon']:
                        for tag in sid_wid_tag[sid][wid]:
                            try:
                                MLSentiCon += (ss_resource_sent[tag]['MLSentiCon']['Positive'] + 
                                               -1*ss_resource_sent[tag]['MLSentiCon']['Negative'])
                            except:
                                MLSentiCon += 0
                                print "failed to add to MLSentiCon"
                            score += MLSentiCon
                        sentitooltip = """ MLSentiCon: %0.3f; """ % (MLSentiCon,)


                    elif senti == ['sentiwn']:
                        for tag in sid_wid_tag[sid][wid]:
                            try:
                                SentiWN += (ss_resource_sent[tag]['SentiWN']['Positive'] +
                                            -1*ss_resource_sent[tag]['SentiWN']['Negative'])
                            except:
                                SentiWN += 0

                            score += SentiWN

                        sentitooltip = cgi.escape(" SentiWN: %0.3f; " % SentiWN, quote=True)

                    else:
                        sentitooltip = ""
                    #########################################################
                    # END OF SENTIMENT (PRINTING BELOW)
                    #########################################################

                    html_word = cgi.escape(wid_info[0], quote=True)
                    html_lemma = cgi.escape(wid_info[1], quote=True)
                    html_pos = cgi.escape(wid_info[2], quote=True)

                    tags_tooltip = ""
                    if len(sid_wid_tag[sid][wid]) > 0:
                        tags_tooltip += "Concept(s):"
                        for tag in sid_wid_tag[sid][wid]:
                            tags_tooltip += """%s """ % (tag)


                    href_word = '<a href="%s?mode=wordview&' % (selfcgi,)
                    href_word += "searchlang=%s&sid=%s&" % (searchlang, sid)
                    href_word += "lemma=%s&postag=%s&" % (html_lemma, html_pos)
                    href_word += "word=%s" % (html_word,)

                    if len(sid_wid_tag[sid][wid]) > 0:
                        for i, tag in enumerate(sid_wid_tag[sid][wid]):
                            href_word += "&wordtag[]=%s" % (tag,)
                            wordcid = sid_wid_cid[sid][wid][i]
                            html_wordclemma = cgi.escape(sid_cid_clemma[sid][wordcid],quote=True)
                            href_word += "&wordclemma[]=%s" % (html_wordclemma,)
                    href_word += '"'

                    if  wid in sid_cid_wid[sid][cid]:
                        href_word += """ class='largefancybox 
                                         fancybox.iframe match'>%s</a>""" % (html_word)
                    else:
                        href_word += """ class='largefancybox fancybox.iframe'
                        style='color:black;text-decoration:none;'>%s</a>""" % (html_word)


                    ###############################################################
                    # SENTIMENT STYLE OPTIONS: coulds, boxes, default:underlined
                    ###############################################################
                    if 'sentiwn' in senti or 'mlsenticon' in senti or senti == 'comp':
                        # DISPLAY BY BACKGROUND BOXES
                        style = ""
                        if score > 0:
                            style = """style="background: linear-gradient(to right, 
                            rgba(51, 168, 255, %f), rgba(51, 168, 255, %f)); 
                            border-radius: 7px; padding: 0px 5px 0px 5px;"
                            """ % (0.3+score, 0.3+score)
                        elif score < 0:
                            if score < -0.3:
                                score += 0.3
                            style = """ style="background: linear-gradient(to right, 
                            rgba(255, 105, 4, %f), rgba(255, 105, 4, %f)); 
                            border-radius: 7px; padding: 0px 5px 0px 5px;"
                            """ % (0.4+abs(score), 0.4+abs(score))

                        s_string += """<span class="tooltip-bottom"
                        data-tooltip="Lemma: %s; POS: %s; %s %s"
                        %s >%s</span> """ % (html_lemma, html_pos, 
                                          tags_tooltip, sentitooltip, style, href_word)

                    # IF NO SENTIMENT
                    else:
                        s_string += """<span class="tooltip-bottom" 
                        data-tooltip="Lemma: %s; POS: %s; %s"
                        >%s</span> """ % (html_lemma, html_pos, 
                                                    tags_tooltip, href_word)


                print """<td>%s""" % s_string


                ############################ TRIAL
                # sid hold the original sentence id
                # links[lang][original_sid] outputs a set of translation sids
                for lang2 in langs2:
                    print "<p>"

                    for lsid in links[lang2][int(sid)]:

#####HERE!!! IF SENTENCE HAS NO WORDS, THEN IT CANNOT BE PRINTED!
                        if len(l_sid_wid[lang2][lsid].keys()) == 0:
                            # then this means there will be no words to print
                            s_string = l_sid_fullsent[lang2][lsid]
                        else:
                            s_string = ""


                        for wid, wid_info in l_sid_wid[lang2][lsid].items():


                            ########################################################
                            # SENTIMENT
                            ########################################################
                            score = 0
                            MLSentiCon = 0
                            SentiWN = 0
                            if senti == 'comp':
                                for tag in l_sid_wid_tag[lang2][sid][wid]:
                                    try:
                                        MLSentiCon += (ss_resource_sent[tag]['MLSentiCon']['Positive'] + 
                                                       -1*ss_resource_sent[tag]['MLSentiCon']['Negative'])
                                    except:
                                        # print "failed to add to MLSentiCon" #TEST
                                        MLSentiCon += 0
                                    try:
                                        SentiWN += (ss_resource_sent[tag]['SentiWN']['Positive'] +
                                                  -1*ss_resource_sent[tag]['SentiWN']['Negative'])
                                    except:
                                        # print "failed to add to SentiWN" #TEST
                                        SentiWN += 0
                                    score += (MLSentiCon + SentiWN)

                                sentitooltip = """ MLSentiCon: %0.3f;  SentiWN: %0.3f; """ % (MLSentiCon, SentiWN)

                            elif senti == ['mlsenticon']:
                                for tag in l_sid_wid_tag[lang2][sid][wid]:
                                    try:
                                        MLSentiCon += (ss_resource_sent[tag]['MLSentiCon']['Positive'] + 
                                                       -1*ss_resource_sent[tag]['MLSentiCon']['Negative'])
                                    except:
                                        MLSentiCon += 0
                                        print "failed to add to MLSentiCon"
                                    score += MLSentiCon
                                sentitooltip = """ MLSentiCon: %0.3f; """ % (MLSentiCon,)


                            elif senti == ['sentiwn']:
                                for tag in l_sid_wid_tag[lang2][sid][wid]:
                                    try:
                                        SentiWN += (ss_resource_sent[tag]['SentiWN']['Positive'] +
                                                    -1*ss_resource_sent[tag]['SentiWN']['Negative'])
                                    except:
                                        SentiWN += 0

                                    score += SentiWN

                                sentitooltip = cgi.escape(" SentiWN: %0.3f; " % SentiWN, quote=True)

                            else:
                                sentitooltip = ""

                            #########################################################
                            # END OF SENTIMENT (PRINTING BELOW)
                            #########################################################



                            html_word = cgi.escape(wid_info[0], quote=True)
                            html_lemma = cgi.escape(wid_info[1], quote=True)
                            html_pos = cgi.escape(wid_info[2], quote=True)

                            tags_tooltip = ""
                            if len(l_sid_wid_tag[lang2][lsid][wid]) > 0:
                                tags_tooltip += "Concept(s):"
                                for tag in l_sid_wid_tag[lang2][lsid][wid]:
                                    tags_tooltip += """%s """ % (tag)


                            href_word = """<a href="%s?mode=wordview&""" % (selfcgi,)
                            href_word += """searchlang=%s&sid=%s&""" % (lang2,sid)
                            href_word += """lemma=%s&postag=%s&""" % (html_lemma,
                                                                       html_pos)
                            href_word += """word=%s""" % (html_word,)

                            if len(l_sid_wid_tag[lang2][lsid][wid]) > 0:
                                for tag in l_sid_wid_tag[lang2][lsid][wid]:
                                    href_word += """&wordtag[]=%s""" % (tag,)
                            href_word += '"'

                            href_word += """ class='largefancybox 
                                                    fancybox.iframe'
                                style='color:black;text-decoration:none;'
                                >%s</a>""" % (html_word)


                            ###############################################################
                            # SENTIMENT STYLE OPTIONS: coulds, boxes, default:underlined
                            ###############################################################
                            if 'sentiwn' in senti or 'mlsenticon' in senti or senti == 'comp':

                                # DISPLAY BY BACKGROUND BOXES
                                style = ""
                                if score > 0:
                                    style = """style="background: linear-gradient(to right, 
                                    rgba(51, 168, 255, %f), rgba(51, 168, 255, %f)); border-radius: 7px; padding: 0px 5px 0px 5px;"
                                    """ % (0.3+score, 0.3+score)
                                elif score < 0:
                                    if score < -0.3:
                                        score += 0.3
                                    style = """ style="background: linear-gradient(to right, 
                                    rgba(255, 105, 4, %f), rgba(255, 105, 4, %f)); border-radius: 7px; padding: 0px 5px 0px 5px;"
                                    """ % (0.4+abs(score), 0.4+abs(score))

                                s_string += """<span class="tooltip-bottom" 
                                data-tooltip="Lemma: %s; POS: %s; %s %s"
                                %s >%s</span> """ % (html_lemma, html_pos, 
                                                  tags_tooltip, sentitooltip, style, href_word)

                            # IF NO SENTIMENT
                            else:

                                s_string += """<span class="tooltip-bottom" 
                                data-tooltip="Lemma: %s; POS: %s; %s"
                                >%s</span> """ % (html_lemma, html_pos, 
                                                    tags_tooltip, href_word)

                        print "%s" % s_string

                        print """<span title='%s'><sub>(%s)</sub>
                                 </span>""" % (lsid,lang2)
                    print "</p>"
                    ################ END TRIAL



                # THIS PRINTS THE UGLY LINE
                # sentiment += """);"></div>"""
                # if 'sentiwn' in senti or 'mlsenticon' in senti or senti == 'comp':
                #     print sentiment

                print """</td>"""
                print """</tr>"""
        print "</table>"

    #############################################
    # WORD-BASED SEARCH (NO CONCEPT RESTRICTION)
    #############################################
    elif len(sid_wid.keys()) > 0:
        count = 0
        for sid in sid_wid.keys():
            for wid, wid_info in sid_wid[sid].items():
                if wid in sid_matched_wid[sid]:
                    count += 1
        print "<b>%d Results for: </b>" % count
        print searchquery[:-1]


        print("""<table class="striped tight">""")
        print("""<thead><tr><th>Sid</th><th>Sentence</th></tr></thead>""")

        for sid in sorted(sid_wid.keys()):
            print """<tr>"""
            # print """<td>%s</td>""" % sid

            print """<td><a class='largefancybox fancybox.iframe' 
            href='%s?corpus=%s&sid=%d&lemma=%s'>%s</a></td>
            """ % (showsentcgi, searchlang, sid, '', sid)

            # print """<td>%s</td>""" % sid_wid[sid].items() #TEST

            s_string = ""
            for wid, wid_info in sid_wid[sid].items():

                ########################################################
                # SENTIMENT
                ########################################################
                score = 0
                MLSentiCon = 0
                SentiWN = 0
                if senti == 'comp':
                    for tag in sid_wid_tag[sid][wid]:
                        try:
                            MLSentiCon += (ss_resource_sent[tag]['MLSentiCon']['Positive'] + 
                                           -1*ss_resource_sent[tag]['MLSentiCon']['Negative'])
                        except:
                            # print "failed to add to MLSentiCon" #TEST
                            MLSentiCon += 0
                        try:
                            SentiWN += (ss_resource_sent[tag]['SentiWN']['Positive'] +
                                      -1*ss_resource_sent[tag]['SentiWN']['Negative'])
                        except:
                            # print "failed to add to SentiWN" #TEST
                            SentiWN += 0
                        score += (MLSentiCon + SentiWN)

                    sentitooltip = """ MLSentiCon: %0.3f;  SentiWN: %0.3f; """ % (MLSentiCon, SentiWN)

                elif senti == ['mlsenticon']:
                    for tag in sid_wid_tag[sid][wid]:
                        try:
                            MLSentiCon += (ss_resource_sent[tag]['MLSentiCon']['Positive'] + 
                                           -1*ss_resource_sent[tag]['MLSentiCon']['Negative'])
                        except:
                            MLSentiCon += 0
                            print "failed to add to MLSentiCon"
                        score += MLSentiCon
                    sentitooltip = """ MLSentiCon: %0.3f; """ % (MLSentiCon,)


                elif senti == ['sentiwn']:
                    for tag in sid_wid_tag[sid][wid]:
                        try:
                            SentiWN += (ss_resource_sent[tag]['SentiWN']['Positive'] +
                                        -1*ss_resource_sent[tag]['SentiWN']['Negative'])
                        except:
                            SentiWN += 0

                        score += SentiWN

                    sentitooltip = cgi.escape(" SentiWN: %0.3f; " % SentiWN, quote=True)

                else:
                    sentitooltip = ""
                #########################################################
                # END OF SENTIMENT (PRINTING BELOW)
                #########################################################


                html_word = cgi.escape(wid_info[0], quote=True)
                html_lemma = cgi.escape(wid_info[1], quote=True)
                html_pos = cgi.escape(wid_info[2], quote=True)

                tags_tooltip = ""
                if len(sid_wid_tag[sid][wid]) > 0:
                    tags_tooltip += "Concept(s):"
                    for tag in sid_wid_tag[sid][wid]:
                        tags_tooltip += """%s """ % (tag)


                href_word = """<a href="%s?mode=wordview&""" % (selfcgi,)
                href_word += """searchlang=%s&sid=%s&""" % (searchlang,sid)
                href_word += """lemma=%s&postag=%s&""" % (html_lemma,
                                                           html_pos)
                href_word += """word=%s""" % (html_word,)
                if len(sid_wid_tag[sid][wid]) > 0:
                    for tag in sid_wid_tag[sid][wid]:
                        href_word += """&wordtag[]=%s""" % (tag,)
                href_word += '"'


                # sid_matched_wid[sid] has a list of wid that should be matches!
                # if highlight:
                if wid in sid_matched_wid[sid]:
                    href_word += """ class='largefancybox fancybox.iframe 
                    match'>%s</a>""" % (html_word)
                else:
                    href_word += """ class='largefancybox fancybox.iframe'
                    style='color:black;text-decoration:none;'
                    >%s</a>""" % (html_word)


                ###############################################################
                # SENTIMENT STYLE OPTIONS: coulds, boxes, default:underlined
                ###############################################################
                if 'sentiwn' in senti or 'mlsenticon' in senti or senti == 'comp':

                    # DISPLAY BY BACKGROUND BOXES
                    style = ""
                    if score > 0:
                        style = """style="background: linear-gradient(to right, 
                        rgba(51, 168, 255, %f), rgba(51, 168, 255, %f)); border-radius: 7px; padding: 0px 5px 0px 5px;"
                        """ % (0.3+score, 0.3+score)
                    elif score < 0:
                        if score < -0.3:
                            score += 0.3
                        style = """ style="background: linear-gradient(to right, 
                        rgba(255, 105, 4, %f), rgba(255, 105, 4, %f));  border-radius: 7px; padding: 0px 5px 0px 5px;"
                        """ % (0.4+abs(score), 0.4+abs(score))

                    s_string += """<span class="tooltip-bottom" 
                    data-tooltip="Lemma: %s; POS: %s; %s %s"
                    %s >%s</span> """ % (html_lemma, html_pos, 
                                      tags_tooltip, sentitooltip, style, href_word)

                # IF NO SENTIMENT
                else:
                    s_string += """<span class="tooltip-bottom" 
                    data-tooltip="Lemma: %s; POS: %s; %s">%s</span> """ % (html_lemma, html_pos, 
                                         tags_tooltip, href_word)


            print """<td>%s""" % s_string



            ############################ TRIAL
            # sid hold the original sentence id
            # links[lang][original_sid] outputs a set of translation sids
            for lang2 in langs2:

                errlog.write("When printing, lang2 = '%s'\n" %(lang2)) #LOG

                print "<p>"

                #BUG!!! links.keys() only has 1 lang, even though langs2 has 2
                errlog.write("lsid list = '%s'\n" % '|'.join(links.keys())) #LOG
                for lsid in links[lang2][int(sid)]:
                    errlog.write("Found a lsid = '%d'\n" %(lsid)) #LOG

                    if len(l_sid_wid[lang2][lsid].keys()) == 0:
                        # then this means there will be no words to print
                        s_string = l_sid_fullsent[lang2][lsid]
                    else:
                        s_string = ""

                    for wid, wid_info in l_sid_wid[lang2][lsid].items():

                        ########################################################
                        # SENTIMENT
                        ########################################################
                        score = 0
                        MLSentiCon = 0
                        SentiWN = 0
                        if senti == 'comp':
                            for tag in l_sid_wid_tag[lang2][sid][wid]:
                                try:
                                    MLSentiCon += (ss_resource_sent[tag]['MLSentiCon']['Positive'] + 
                                                   -1*ss_resource_sent[tag]['MLSentiCon']['Negative'])
                                except:
                                    # print "failed to add to MLSentiCon" #TEST
                                    MLSentiCon += 0
                                try:
                                    SentiWN += (ss_resource_sent[tag]['SentiWN']['Positive'] +
                                              -1*ss_resource_sent[tag]['SentiWN']['Negative'])
                                except:
                                    # print "failed to add to SentiWN" #TEST
                                    SentiWN += 0
                                score += (MLSentiCon + SentiWN)

                            sentitooltip = """ MLSentiCon: %0.3f;  SentiWN: %0.3f; """ % (MLSentiCon, SentiWN)

                        elif senti == ['mlsenticon']:
                            for tag in l_sid_wid_tag[lang2][sid][wid]:
                                try:
                                    MLSentiCon += (ss_resource_sent[tag]['MLSentiCon']['Positive'] + 
                                                   -1*ss_resource_sent[tag]['MLSentiCon']['Negative'])
                                except:
                                    MLSentiCon += 0
                                    print "failed to add to MLSentiCon"
                                score += MLSentiCon
                            sentitooltip = """ MLSentiCon: %0.3f; """ % (MLSentiCon,)


                        elif senti == ['sentiwn']:
                            for tag in l_sid_wid_tag[lang2][sid][wid]:
                                try:
                                    SentiWN += (ss_resource_sent[tag]['SentiWN']['Positive'] +
                                                -1*ss_resource_sent[tag]['SentiWN']['Negative'])
                                except:
                                    SentiWN += 0

                                score += SentiWN

                            sentitooltip = cgi.escape(" SentiWN: %0.3f; " % SentiWN, quote=True)

                        else:
                            sentitooltip = ""

                        #########################################################
                        # END OF SENTIMENT (PRINTING BELOW)
                        #########################################################

                        html_word = cgi.escape(wid_info[0], quote=True)
                        html_lemma = cgi.escape(wid_info[1], quote=True)
                        html_pos = cgi.escape(wid_info[2], quote=True)

                        tags_tooltip = ""
                        if len(l_sid_wid_tag[lang2][lsid][wid]) > 0:
                            tags_tooltip += "Concept(s):"
                            for tag in l_sid_wid_tag[lang2][lsid][wid]:
                                tags_tooltip += """%s """ % (tag)


                        href_word = """<a href="%s?mode=wordview&""" % (selfcgi,)
                        href_word += """searchlang=%s&sid=%s&""" % (lang2,sid)
                        href_word += """lemma=%s&postag=%s&""" % (html_lemma,
                                                                   html_pos)
                        href_word += """word=%s""" % (html_word,)

                        if len(l_sid_wid_tag[lang2][lsid][wid]) > 0:
                            for tag in l_sid_wid_tag[lang2][lsid][wid]:
                                href_word += """&wordtag[]=%s""" % (tag,)
                        href_word += '"'

                        href_word += """ class='largefancybox fancybox.iframe'
                            style='color:black;text-decoration:none;'
                            > %s </a>""" % (html_word)


                        ###############################################################
                        # SENTIMENT STYLE OPTIONS: coulds, boxes, default:underlined
                        ###############################################################
                        if 'sentiwn' in senti or 'mlsenticon' in senti or senti == 'comp':
                            # DISPLAY BY BACKGROUND BOXES
                            style = ""
                            if score > 0:
                                style = """style="background: linear-gradient(to right, 
                                rgba(51, 168, 255, %f), rgba(51, 168, 255, %f)); border-radius: 7px; padding: 0px 5px 0px 5px;"
                                """ % (0.3+score, 0.3+score)
                            elif score < 0:
                                if score < -0.3:
                                    score += 0.3
                                style = """ style="background: linear-gradient(to right, 
                                rgba(255, 105, 4, %f), rgba(255, 105, 4, %f));  border-radius: 7px; padding: 0px 5px 0px 5px;"
                                """ % (0.4+abs(score), 0.4+abs(score))

                            s_string += """<span class="tooltip-bottom" 
                            data-tooltip="Lemma: %s; POS: %s; %s %s"
                            %s >%s</span> """ % (html_lemma, html_pos, 
                                              tags_tooltip, sentitooltip, style, href_word)

                        # IF NO SENTIMENT
                        else:
                            s_string += """<span class="tooltip-bottom" 
                            data-tooltip="Lemma: %s&#10; POS: %s &#10; %s %s">%s</span> """ % (html_lemma, html_pos, 
                                                 tags_tooltip, sentitooltip,href_word)


                    print "%s" % s_string

                    print """<span title='%s'><sub>(%s)</sub>
                             </span>""" % (lsid,lang2)

                    errlog.write("langs2:%s lsid=%d\n" %(lang2, lsid)) #LOG


                print "</p>"


            print """</td>"""
            print """</tr>"""

        print "</table>"

    else:
        print "Nothing found!"

except:
    print "<br>"
    print "<h6> Welcome! Please query the database!</h6>"


##########################################
# SEARCH FORM!
###########################################
print """<hr>"""
# START FORM
print("""<form action="" id="newquery" method="post">""")

# SEARCH LANGUAGE
print("""<p style="line-height: 35px"><nobr>
          Language: <select name="searchlang" id="corpuslang" style="font-size:80%" >""")
for l in corpuslangs:
    if l == searchlang:
        print("""<option value ='%s' selected>%s</option>""" % (l, omwlang.trans(l, 'eng')))
    else:
        print("""<option value ='%s'>%s</option>""" % (l, omwlang.trans(l, 'eng')))
print("""</select>""")

# MULTISELECT FOR LANGS2
print """<select id="langs2" name="langs2" multiple="multiple">"""
for l in corpuslangs:
    if l in langs2:
        print """<option value='%s' selected>%s</option>
              """ % (l, omwlang.trans(l, 'eng'))
    else:
        print """<option value='%s'>%s</option>
              """ % (l, omwlang.trans(l, 'eng'))
print """</select>
        <script>
            $('#langs2').multipleSelect({
                placeholder: "Align with: (langs)",
                width: "13em"
            });
        </script>"""

print """&nbsp;&nbsp;</nobr> """
# TAG
print("""<nobr>Concept:""")
print("""<input name="concept" id="idconcept" size="9" pattern="None|x|e|w|loc|org|per|dat|oth|[<>=~!]?[0-9]{8}-[avnrxz]" title = "xxxxxxxx-a/v/n/r/x/z |x|e|w|loc|org|per|dat|oth" style="font-size:80%%" placeholder="%s"/>&nbsp;&nbsp;</nobr>""" % ph_concept)

# CLEMMA
print("""<nobr>C-lemma:""")
print("""<input name="clemma" size="12" title="Please Insert a Concept Lemma"  
         style="font-size:80%%" placeholder="%s"/>&nbsp;&nbsp;</nobr>""" % ph_clemma)

# WORD
print("""<nobr>Word:""")
print("""<input name="word" size="12" title="Please Insert a Word"  
         style="font-size:80%%" placeholder="%s"/>&nbsp;&nbsp;</nobr>""" % ph_word)

# LEMMA
print("""<nobr>Lemma:""")
print("""<input name="lemma" size="12" title="Please Insert a Lemma"  style="font-size:80%%" placeholder="%s"/></nobr>""" % ph_lemma)


# SID_FROM & SID_TO
print("""<nobr>SID (from):""")
if sid_from != 0:
    print("""<input name="sid_from" size="12" title="Minimum SID Allowed" 
    style="font-size:80%%" value="%s" />""" % sid_from)
else:
    print("""<input name="sid_from" size="12" title = "Minimum SID Allowed" 
    style="font-size:80%"/>""")
print("""SID (to):""")
if sid_to != 1000000:    
    print("""<input name="sid_to" size="12" title="Maximum SID Allowed" 
    style="font-size:80%%" value="%d"/>&nbsp;&nbsp;</nobr>""" % sid_to)
else:
    print("""<input name="sid_to" size="12" title="Maximum SID Allowed" 
    style="font-size:80%"/>&nbsp;&nbsp;</nobr>""")


# SENTIMENT
print("""<nobr>Sentiment:""")
if senti == 'comp':
    print("""<input type="checkbox" name="senti[]" value="mlsenticon" 
              id="senticheck" checked/>
             <label for="senticheck1" class="inline">MLSentiCon</label> 
             <input type="checkbox" name="senti[]" value="sentiwn" 
              id="senticheck" checked/>
             <label for="senticheck2" class="inline">SentiWN</label>&nbsp;&nbsp;</nobr>""")
elif senti == ['mlsenticon']:
    print("""<input type="checkbox" name="senti[]" value="mlsenticon" 
              id="senticheck" checked/>
             <label for="senticheck1" class="inline">MLSentiCon</label> 
             <input type="checkbox" name="senti[]" value="sentiwn" 
              id="senticheck" />
             <label for="senticheck2" class="inline">SentiWN</label>&nbsp;&nbsp;</nobr>""")
elif senti == ['sentiwn']:
    print("""<input type="checkbox" name="senti[]" value="mlsenticon" 
              id="senticheck" />
             <label for="senticheck1" class="inline">MLSentiCon</label> 
             <input type="checkbox" name="senti[]" value="sentiwn" 
              id="senticheck" checked/>
             <label for="senticheck2" class="inline">SentiWN</label>&nbsp;&nbsp;</nobr>""")
else:
    print("""<input type="checkbox" name="senti[]" value="mlsenticon" id="senticheck" />
         <label for="senticheck1" class="inline">MLSentiCon</label> 
         <input type="checkbox" name="senti[]" value="sentiwn" id="senticheck" />
         <label for="senticheck2" class="inline">SentiWN</label>&nbsp;&nbsp;</nobr>""")



# SHOWS POS SELECT AND HELP DIV PER LANGUAGE (HIDDEN/TRIGGERED BY
# SELECTING A LANGUAGE ABOVE)
for l in corpuslangs:
    print """<nobr><span id="pos-%s" class="defaulthide">POS:""" % l
    print """<select id="selectpos-%s" name="selectpos-%s" 
              multiple="multiple">""" % (l, l)

    maxlenght = 7 # used to figure out the width of the select
    for p in sorted(pos_tags[l].keys()):
        if len(p) > maxlenght:
            maxlenght = len(p)

        if p in pos_form[searchlang]:
            print """<option value ='%s' selected>%s</option>
              """ % (cgi.escape(p, quote=True), cgi.escape(p, quote=True))
        else:
            print """<option value ='%s'>%s</option>
              """ % (cgi.escape(p, quote=True), cgi.escape(p, quote=True))

    print """</select>
        <script>
            $('#selectpos-%s').multipleSelect({
                placeholder: "Select POS",
                width: "%dem"
            });
        </script>""" % (l, maxlenght+2)

    print("""<a class='fancybox' href='#postags-%s' 
          style='color:black;text-decoration:none;'><!--
          --><sup>?</sup></a></span></nobr>""" % l)

# SEARCH LIMITS
print """<nobr>Limit: <select name="limit" style="font-size:80%">"""
for value in ['10','25','50','100','all']:
    if value == limit:
        print """<option value ='%s' selected>%s</option>""" % (value, value)
    else:
        print """<option value ='%s'>%s</option>""" % (value, value)
print """</select>&nbsp;&nbsp;</nobr>"""


# SUBMIT BUTTON
print """<button class="small"> <a href="javascript:{}"
         onclick="document.getElementById('newquery').submit(); 
         return false;"><span title="Search">
         <span style="color: #4D99E0;"><i class='icon-search'></i>
         </span></span></a></button></p>"""
print """</form>"""




####################################
# FOOTER
####################################
print """<hr><a href='%s'>More detail about the %s (%s)</a>
      """ % (url, cginame, ver)
print '<p>Developers:'
print ' <a href="">Luís Morgado da Costa</a> '
print '&lt;<a href="mailto:lmorgado.dacosta@gmail.com">lmorgado.dacosta@gmail.com</a>&gt;'
print '; '
print ' <a href="http://www3.ntu.edu.sg/home/fcbond/">Francis Bond</a> '
print '&lt;<a href="mailto:bond@ieee.org">bond@ieee.org</a>&gt;'


####################################
# INVISIBLE DIV FOR POS TAGS HELPER
####################################
for l in corpuslangs:
    print("""<div id="postags-%s" style="display: none;">
                <h3>%s's POS Tags</h3>""" % (l, omwlang.trans(l, 'eng')))
    for p, info in sorted(pos_tags[l].items()):
        print( """<b>%s:</b> <span title='%s'> %s</span>
                  <br>""" % (p, info['eng_def'], info['def']))
    print("""</div>""")

print "  </body>"
print "</html>"

errlog.close()


######################################################################
