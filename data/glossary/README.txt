PHRASEBOOK FILES
Put .csv or .json files here. They are loaded when the app starts and when you press "Sync cloud data now" in Setup.
Files whose name starts with _ (like _example.csv) are ignored: copy it, rename it (e.g. health.csv), fill it in.

Shape 1 (one column per language, one row per phrase). Leave a cell empty if you do not have that language yet:
    en,am,om,wal
    Where is the clinic?,ክሊኒኩ የት ነው?,Kiliniikni eessa jira?,
Shape 2 (one translation per row):
    source_lang,target_lang,source_text,translation
    en,wal,Hello,<your Wolaytta text>

Language codes: en am om ti so aa wal sid ktb hdy gmv sgw har anu gez ... (full list in Setup).
IMPORTANT: for languages no machine engine supports (wal, sid, ktb, hdy, gmv, sgw, har, anu, gez, aa)
your data is the ONLY source. Have a fluent speaker write or review every phrase.
Matching is exact on the whole phrase (case and final punctuation ignored): it is a lookup table, not a translator.
