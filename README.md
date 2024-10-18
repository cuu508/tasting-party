# Tasting Party

`scan.py` visits sites listed in sites.txt, and records the
cookies they set on first visit. In the end, it generates a report
in `site/index.html` with the results.

Example report: https://sīkdatnes.lv/

To use, first install Chromium (the below assumes Debian):

```
apt install chromium chromium-chromedriver
```

Then set up python virtualenv, then install dependencies:

```
pip install -r requirements.txt
```

And then run `scan.py`:

```
python scan.py
```

The script uses Chromium to visit the sites (so you need Chromium installed),
and talks to Chrome using the selenium library. For each visited site it:

* loads the page,
* waits 3 seconds,
* sends the "End" key to scroll to the bottom of the page,
* waits 3 more seconds,
* takes note of what cookies are set.


