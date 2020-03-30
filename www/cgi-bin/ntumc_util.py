#!/usr/bin/env python
# -*- coding: utf-8 -*-

import cgi
#import cgitb; cgitb.enable()  # for troubleshooting
from html import escape as html_escape
import sys
import time

#sys.stdout = codecs.getwriter('utf8')(sys.stdout)


# (Wilson) Disable pylint warnings complaining about OTB-style indents
# pylint: disable=bad-continuation

#############################################################
# Configuration
#############################################################
#tagcgi = 'tag-lex.cgi' # DEPRECATED - WILL BE REMOVED SOON
taglcgi = 'tag-lexs.cgi'
tagwcgi = 'tag-word.cgi'
showsentcgi = 'show-sent.cgi'
logincgi = 'login.cgi'
### reference to wn-grid (search .cgi)
omwcgi = 'wn-gridx.cgi'
# wordnets
wncgi = 'wn-gridx.cgi'
wndb = '../db/wn-ntumc.db'

#############################################################
# Utilities for debugging
#############################################################

def jilog(msg):
    # Author: Tuan Anh (2014-06-12)
    msg_ascii = msg.decode('utf-8').encode('ascii', 'ignore')
    sys.stderr.write(msg_ascii)

    try:
        with open('../log/ntumc.txt', 'a', encoding='utf-8') as logfile:
            logfile.write(msg)

    except BaseException as ex:
        exclass = ex.__class__.__name__
        sys.stderr.write(f'{exclass}: {str(ex)}')


class Timer:
    """Timer class for performance optimisation
    TODO(Wilson): Refactor __str__ into __repr__ and log()
    """
    def __init__(self):
        self.start_time = time.time()
        self.end_time = time.time()
    def start(self):
        self.start_time = time.time()
        return self
    def stop(self):
        self.end_time = time.time()
        return self
    def __str__(self):
        return 'Execution time: %.2f sec(s)' % (self.end_time - self.start_time)
    def log(self, task_note=''):
        jilog(u'%s - Note=[%s]\n' % (self, task_note))
        return self


#############################################################
# NTU-MC shared functions
#############################################################

def expandlem(lemma):
    """Note: keep in sync with tag-lexs

    TODO(Wilson): Check what is the purpose of those replace() targets, they're
                  really weird!
    """
    lems = set(
        lemma,
        lemma.lower(),
        lemma.upper(),
        lemma.title(),
    )
    for old, new in [
            ('-', ''),
            ('-', '_'),
            (' ', '-'),
            ('_', ''),
            (' ', ''),
            # ('_', u'∥'),
            # ('-', u'∥'),
            # (' ', u'∥'),
            # (u'・', u'∥'),
            # (u'ー', u'∥'),
    ]:
        lems.add(lemma.replace(old, new))
    return lems


def pos2wn(pos, lang, lemma=''):
    """Maps the given pos to its WordNet equivalent

    FIXME: check and document --- Change POS for VN?

    Params:
    pos: str - Local POS tag.
    lang: str - Local language code.
    lemma: str - Lemma that the POS is for. Used when the lemma precludes
                 certain POS tags.
    """
    def pos2wn_jpn(pos, lemma):
        if (pos in [u'名詞-形容動詞語幹', u'形容詞-自立', u'連体詞']
                and lemma not in [u'この', u'その', u'あの']):
            return 'a'
        
        for poswn, poslist in {
            'n': """名詞-サ変接続
                    名詞-ナイ形容詞語幹
                    名詞-一般
                    名詞-副詞可能
                    名詞-接尾-一般
                    名詞-形容動詞語幹
                    名詞-数
                    記号-アルファベット""",
            'v': '動詞-自立',
            'r': '副詞-一般  副詞-助詞類接続',
        }:
            if pos in poslist.split():
                return poswn
        return 'x'

    def pos2wn_eng(pos, lemma):
        if pos in 'CD  NN  NNS  NNP  NNPS  WP  PRP'.split():
            # includes proper nouns and pronouns
            # FIXME: flag for proper nouns
            return 'n'
        if pos == 'VAX':  #local tag for auxiliaries
            return 'x'
        if pos.startswith('V'):
            return 'v'
        if (pos.startswith('J')
                or pos in 'WDT  WP$  PRP$  PDT  PRP'.split()
                or (pos == 'DT' and lemma not in ['a', 'an', 'the'])):  # most determiners
            return 'a'
        if pos.startswith('RB') or pos == 'WRB':
            return 'r'
        return 'x'

    def pos2wn_cmn(pos, lemma):
        for poswn, poslist in {
            'n': 'NN  NN2  CD  DT  PN  PN2  LC  M  M2  NR  NT',
            'v': 'VV  VV2  VC  VE',
            'a': 'JJ  JJ2  OD  VA  VA2',
            'r': 'AD  AD2  ETC  ON',
        }:
            if pos in poslist.split():
                return poswn
        return 'x'

    def pos2wn_vie(pos, lemma):
        for poswn, poslist in {
            'n': 'N Np Nc Nu Ny B',
            'v': 'V',
            'a': 'A',
            'r': 'L R',
        }:
            if pos in poslist.split():
                return poswn
        return 'x'

    mapper = {
        'jpn': pos2wn_jpn,
        'eng': pos2wn_eng,
        'cmn': pos2wn_cmn,
        'vie': pos2wn_vie,
    }.get(lang)

    if mapper:
        return mapper(pos, lemma)
    return 'u'

#half = u' 0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ!"#$%&()*+,-./:;<=>?@[\\]^_`{|}~'
#full = u'　０１２３４５６７８９ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ！゛＃＄％＆（）＊＋、ー。／：；〈＝〉？＠［\\］＾＿‘｛｜｝～'
#half2full = dict((ord(x[0]), x[1]) for x in zip(half, full)
#full2half = dict((ord(x[0]), x[1]) for x in zip(full, half)
#print u'Hello, world!'.translate(half2full)


###
### Tagging functions
###

# Add more tags in
mtags = ['e', 'x', 'w'] + ['org', 'loc', 'per', 'dat', 'oth', 'num', 'dat:year']
mtags_short = {
    'e': 'e',
    'x': 'x',
    'w': 'w',
    'org': 'Org',
    'loc': 'Loc',
    'per': 'Per',
    'dat': 'Dat',
    'oth': 'Oth',
    'num': 'Num',
    'dat:year': 'Year',
    '': 'Not tagged',
    None : 'Not tagged',
}
# Human-friendly representation of mtags
mtags_human = {
    'e': 'e',
    'x': 'x',
    'w': 'w',
    'org': 'Organization',
    'loc': 'Location',
    'per': 'Person',
    'dat': 'Date/Time',
    'oth': 'Other',
    'num': 'Number',
    'dat:year': 'Date: Year',
    '': 'Not tagged',
    None: 'Not tagged',
}



def template(html, *args, **kwargs):
    """Wraps str.format() with HTML-escaped format args"""
    args = [html_escape(str(arg)) for arg in args]
    for key, val in kwargs.items():
        kwargs[key] = html_escape(str(val))

    return html.format(args, **kwargs)


def tbox(sss, cid, wp, tag, ntag, com):
    """Create the box for tagging entries: return a string

    FIXME(Wilson): Directly formatting strings into html is vuln. to html
                   injection

    Params:
    sss - Synsets?
    cid - Concept id?
    wp - ?
    tag - ?
    ntag - ?
    com - Comment

    TODO(Wilson): Document params
    TODO(Wilson): Since Py3, all strings are natively stored as Unicode. We
                  still have to verify exactly how Python's under-the-hood
                  implementation for Unicode comparison works; i.e. are they
                  compliant with canonical equivalence? See:
                  https://en.wikipedia.org/wiki/Unicode_equivalence
    """
    box = """<span style="background-color: #eeeeee;">"""  ### FIXME cute css div

    for i, t in enumerate(sss):
        # 2012-06-25 [Tuan Anh]
        # Prevent funny wordwrap where label and radio button are placed on
        # different lines
        box += template("""
            <span style="white-space: nowrap; background-color: #dddddd">
              <input type="radio" name="cid_{cid}" value="{t}" {checked} />
              {index}
              <sub><font {fontcol}size="-2">{t_1}</font></sub>
            </span>\n""",
            cid=cid,
            t=t,
            checked='CHECKED' if t == tag else '',
            index=i + 1,
            fontcol='color="DarkRed" ' if wp == t[-1] else '',
            t_1=t[-1]
        )

    for tk in mtags:
        # 2012-06-25 [Tuan Anh]
        # Friendlier tag value display
        box += template("""
            <span style="white-space: nowrap; background-color:#dddddd">
              <input type="radio" name="cid_{cid}" title="{t_hf}" value="{tk}" {checked} />
              <span title="{t_hf}">
                {show_text}
              </span>
            </span>\n""",
            cid=cid,
            t_hf=mtags_human[tk],  # Human-friendly version of tk
            tk=tk,
            checked='CHECKED' if tk == tag else '',
            show_text=mtags_short.get(tk) or tk
        )

    if tag != ntag:
        box += template("""
            <span style="background-color: #dddddd; white-space: nowrap; border: 1px solid black">
              {ntag}
            </span>""",
            ntag=ntag
        )

    # <input style='font-size:12px; background-color: #ececec;'
    #  title='tag' type='text' name='ntag_%s' value='%s' size='%d'
    #  pattern ="loc|org|per|dat|oth|[<>=~!]?[0-9]{8}-[avnr]"
    #  />""" % (cid, tagv, 8)
    box += template("""
        <textarea
          style="font-size:12px; height: 18px; width: 150px; background-color: #ecffec;"
          placeholder="comment (multiline ok)" title="comment" name="com_{cid}">
            {com}
        </textarea>""",
        cid=cid,
        com=com or ''
    )

    box += """</span>"""  ### FIXME cute css div
    return box


###
### Get the synsets for a lemma
###
def lem2ss(cursor, lem, lang):
    """Return a list of possible synsets for lang"""
    lems = list(expandlem(lem))
    lem_placeholders = ','.join(['?'] * len(lems))

    values = lems + [lang]
    sql = f"""
        SELECT DISTINCT synset
        FROM word
        LEFT JOIN sense ON word.wordid = sense.wordid
        WHERE lemma IN ({lem_placeholders})
          AND sense.lang = ?
        ORDER BY freq DESC
    """

    cursor.execute(sql, values)
    rows = cursor.fetchall()

    # Backoff to lang1
    # if not rows and lang != lang1:
    # w.execute("""SELECT distinct synset
    #              FROM word LEFT JOIN sense ON word.wordid = sense.wordid
    #              WHERE lemma in (%s) AND sense.lang = ? and sense.status is not 'old'
    #              ORDER BY freq DESC""" % ','.join('?'*len(lems)), (lems + [lang1]))
    # rows = w.fetchall()
    # com_all='FW:eng'

    ### sort by POS
    return sorted([s[0] for s in rows], key=lambda x: x[-1])


def set_rest_x(cursor, usrname, sid, cid):
    """Sets tag='x' for rows with the given (sid, cid) in tables: cwl, concept

    TODO(Wilson): Document params
    """
    query = """
        UPDATE concept SET tag='x', usrname=?
        WHERE ROWID=(
            SELECT bcon.ROWID
            FROM cwl AS a
            INNER JOIN cwl AS b
              ON a.sid=b.sid AND a.wid=b.wid
            LEFT JOIN concept AS acon
              ON a.sid=acon.sid AND a.cid=acon.cid
            LEFT JOIN concept AS bcon
              ON b.sid=bcon.sid AND b.cid=bcon.cid
            WHERE a.sid=? AND a.cid=? AND acon.tag NOT IN ('x', 'e') AND bcon.tag IS NULL
        )
    """
    cursor.execute(query, (usrname, sid, cid))
