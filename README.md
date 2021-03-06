# IMI

Code for searching and annotating the NTU Multilingual Corpus.  The code is under the MIT license.  The databases may have their own licenses.



We will start with the code for searching.


If you use this, please cite:

Bond, Francis, Luís Morgado da Costa, and Tuấn Anh Lê (2015)
[IMI — A Multilingual Semantic Annotation Environment](https://www.aclweb.org/anthology/P15-4002.pdf). In Proceedings of ACL-IJCNLP 2015 System Demonstrations, Beijing. pp 7–12

```bibtex
@inproceedings{bond-etal-2015-imi,
    title = "{IMI} {---} A Multilingual Semantic Annotation Environment",
    author = "Bond, Francis  and
      Morgado da Costa, Lu{\'\i}s  and
      L{\^e}, Tuấn Anh",
    booktitle = "Proceedings of {ACL}-{IJCNLP} 2015 System Demonstrations",
    month = jul,
    year = "2015",
    address = "Beijing, China",
    publisher = "Association for Computational Linguistics and The Asian Federation of Natural Language Processing",
    url = "https://www.aclweb.org/anthology/P15-4002",
    doi = "10.3115/v1/P15-4002",
    pages = "7--12",
}
```

There is code for exporting the corpus to XML here: https://github.com/lmorgadodacosta/NTUMC





Put something like this in apache2/conf-enabled/httpd.conf
```
### NTUMC
ScriptAlias /ntumc/cgi-bin/ /var/www/ntumc/cgi-bin/
Alias /ntumc/ /var/www/ntumc/html/

<Directory "/ntumc/cgi-bin/">
AddHandler cgi-script .cgi 
AllowOverride All
Options -Indexes, +FollowSymLinks +ExecCGI
Order allow,deny
Allow from all
</Directory>
```