# Letterboxd-to-IMDb
[![GitHub stars](https://img.shields.io/github/stars/TobiasPankner/Letterboxd-to-IMDb.svg?style=social&label=Star)](https://GitHub.com/TobiasPankner/Letterboxd-to-IMDb/stargazers/)
[![Donate](https://img.shields.io/badge/Donate-PayPal-green.svg)](https://www.paypal.com/cgi-bin/webscr?cmd=_s-xclick&hosted_button_id=3TU2XDBK2JFU4&source=url)

- [Prerequisites](#prerequisites)
- [Run the script](#run-the-script)
- [Getting the IMDb cookie](#getting-the-imdb-cookie)
- [Command line options](#command-line-options)

Python script to import your Letterboxd movies into IMDb.

## Prerequisites  
  
 - Python3 ([Download](https://www.python.org/downloads/))  
 - [Letterboxd](https://letterboxd.com/) Account
 - [IMDb](https://www.imdb.com/) account
 
## Run the script
 1. Export your Letterboxd ratings ([How to](https://listy.is/help/how-to-export-letterboxd-watchlists-reviews/))
 2. [Get the IMDb cookie](#getting-the-imdb-cookie) and save it as "cookie.txt" in the script folder
 2. Install dependencies: `pip install -r requirements.txt`
 3. Run letterboxd2imdb.py: `python letterboxd2imdb.py -f <YOUR ZIP FILE>.zip`
 
## Getting the IMDb cookie
**Treat this cookie like your password!**

  1. Log into your IMDb account
  2. Open Chrome dev tools -> Network
  3. Filter by Fetch/XHR
  4. Refresh the page
  5. Copy the cookie of one of the requests (Right click -> Copy Value)
  
  ![Example](https://imgur.com/chRo9wj.jpg)
 
## Command line options
```
usage: letterboxd2imdb.py [-h] -f ZIPFILE [-p PARALLEL] [-r RATING]

Imports your Letterboxd ratings into IMDb

required arguments:
  -f ZIPFILE   The exported zip file from letterboxd

optional arguments:
  -h, --help   show this help message and exit
  -p PARALLEL  Urls to be processed in parallel (valid: 1 to 20)
  -r RATING    The rating to give watched but unrated movies. By default they are ignored (valid: 1 to 10)
```

`-p`: Can be used if you want to speed up the process, if you set it too high you might get rate limited. Default: 5  
`-r`: Can be used to rate watched but unrated movies. Because IMDb doesn't have an option to "just watch", a default rating has to be specified

Advanced usage example:
`py letterboxd2imdb.py -f .\letterboxd-user-2022-02-20-16-16-utc.zip -p 10 -r 5`

