import argparse
import concurrent.futures

import requests
from argparse import ArgumentParser
import csv
import re
from zipfile import ZipFile
from io import TextIOWrapper
from tqdm import tqdm

imdb_cookie = ""


def read_csv(file):
    to_return = []

    reader = csv.DictReader(TextIOWrapper(file, 'utf-8'))
    for row in reader:
        to_return.append(row)
    return to_return


def read_zip(filename):
    with ZipFile(filename, 'r') as letterboxd_file:
        with letterboxd_file.open("ratings.csv", mode='r') as f:
            ratings = read_csv(f)
        with letterboxd_file.open("watched.csv", mode='r') as f:
            watched = read_csv(f)
        with letterboxd_file.open("watchlist.csv", mode='r') as f:
            watchlist = read_csv(f)

    return ratings, watched, watchlist


def get_imdb_id(letterboxd_uri):
    resp = requests.get(letterboxd_uri)
    if resp.status_code != 200:
        return None

    # extract the IMDb url
    re_match = re.findall(r'href=".+title/(tt\d+)/maindetails"', resp.text)
    if not re_match:
        return None

    return re_match[0]


def rate_on_imdb(imdb_id, rating):
    req_body = {
        "query": "mutation UpdateTitleRating($rating: Int!, $titleId: ID!) { rateTitle(input: {rating: $rating, titleId: $titleId}) { rating { value __typename } __typename }}",
        "operationName": "UpdateTitleRating",
        "variables": {
            "rating": rating,
            "titleId": imdb_id
        }
    }
    headers = {
        "content-type": "application/json",
        "cookie": imdb_cookie
    }

    resp = requests.post("https://api.graphql.imdb.com/", json=req_body, headers=headers)

    if resp.status_code != 200:
        raise ValueError(f"Error rating on IMDb. Code: {resp.status_code}")

    json_resp = resp.json()
    if 'errors' in json_resp and len(json_resp['errors']) > 0:
        first_error_msg = json_resp['errors'][0]['message']

        if 'Authentication' in first_error_msg:
            print(f"Failed to authenticate with cookie")
            exit(1)
        else:
            raise ValueError(first_error_msg)


def add_to_imdb_watchlist(imdb_id):
    headers = {
        "content-type": "application/json",
        "cookie": imdb_cookie
    }

    resp = requests.put(f"https://www.imdb.com/watchlist/{imdb_id}", headers=headers)

    if resp.status_code != 200:
        raise ValueError(f"Error adding to IMDb watchlist. Code: {resp.status_code}")

    if resp.status_code == 403:
        print(f"Failed to authenticate with cookie")
        exit(1)


def rate_letterboxd_to_imdb(letterboxd_dict):
    imdb_id = get_imdb_id(letterboxd_dict['Letterboxd URI'])
    if imdb_id is None:
        raise ValueError("Cannot find IMDb title")

    if letterboxd_dict['Action'] == "rate":
        rate_on_imdb(imdb_id, int(float(letterboxd_dict['Rating']) * 2))
    elif letterboxd_dict['Action'] == "watchlist":
        add_to_imdb_watchlist(imdb_id)

    return letterboxd_dict


def main():
    global imdb_cookie

    parser = ArgumentParser(description="Imports your Letterboxd ratings and watchlist into IMDb")
    optional = parser._action_groups.pop()
    required = parser.add_argument_group('required arguments')
    parser.add_argument_group('optional arguments')
    required.add_argument("-f", dest="zipfile", type=str, required=True,
                          help="The exported zip file from letterboxd")
    optional.add_argument("-p", dest="parallel", type=int, default=5,
                          help="Urls to be processed in parallel (valid: 1 to 20)")
    optional.add_argument("-r", dest="rating", type=int, default=0,
                          help="The rating to give watched but unrated movies. By default they are ignored (valid: 1 to 10)")
    optional.add_argument("-w", dest="watchlist", action=argparse.BooleanOptionalAction,
                          help="Add this flag to also transfer your watchlist")
    parser._action_groups.append(optional)

    args = parser.parse_args()

    print(r"""
  _        _   _           _                _   ___   ___ __  __ ___  _    
 | |   ___| |_| |_ ___ _ _| |__  _____ ____| | |_  ) |_ _|  \/  |   \| |__ 
 | |__/ -_)  _|  _/ -_) '_| '_ \/ _ \ \ / _` |  / /   | || |\/| | |) | '_ \
 |____\___|\__|\__\___|_| |_.__/\___/_\_\__,_| /___| |___|_|  |_|___/|_.__/
                                                                           
""")

    try:
        with open('cookie.txt', 'r') as file:
            imdb_cookie = file.read().replace('\n', '').strip()
    except:
        print("Failed to read cookie.txt, have you created the file?")
        exit(1)

    ratings, watched_unfiltered, watchlist = read_zip(args.zipfile)

    to_transfer = []

    print(f"Letterboxd rated: {len(ratings)}")
    to_transfer.extend([dict(w, Action="rate") for w in ratings])

    # filter to get only the watched and unrated entries
    rating_uris = [rating['Letterboxd URI'] for rating in ratings]
    watched = list(filter(lambda w: w['Letterboxd URI'] not in rating_uris, watched_unfiltered))
    print(f"Letterboxd watched: {len(watched)}{'' if args.rating > 0 else ' (ignored, see -r option)'}")
    if args.rating > 0:
        to_transfer.extend([dict(w, Rating=args.rating / 2, Action="rate") for w in watched])

    print(f"Letterboxd watchlist: {len(watchlist)}{'' if args.watchlist else ' (ignored, see -w option)'}\n")
    if args.watchlist:
        to_transfer.extend([dict(w, Action="watchlist") for w in watchlist])

    success = []
    errors = []

    with tqdm(total=len(to_transfer)) as pbar:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as executor:
            future_to_url = {
                executor.submit(rate_letterboxd_to_imdb, letterboxd_dict): letterboxd_dict for letterboxd_dict in to_transfer
            }
            try:
                for future in concurrent.futures.as_completed(future_to_url):
                    letterboxd_dict = future_to_url[future]
                    pbar.update(1)
                    try:
                        success.append(future.result())
                    except Exception as e:
                        errors.append({"letterboxd_dict": letterboxd_dict, "error": e})
            except KeyboardInterrupt:
                executor._threads.clear()
                concurrent.futures.thread._threads_queues.clear()

    ratings_success = [s for s in success if s['Action'] == 'rate']
    watchlist_success = [s for s in success if s['Action'] == 'watchlist']
    print(f"\nSuccessfully rated: {len(ratings_success)} ")
    print(f"Successfully added to watchlist: {len(watchlist_success)} ")

    ratings_error = [e for e in errors if e['letterboxd_dict']['Action'] == 'rate']
    watchlist_error = [e for e in errors if e['letterboxd_dict']['Action'] == 'watchlist']
    print(f"{len(ratings_error)} rating errors")
    for error in ratings_error:
        print(f"\t{error['letterboxd_dict']['Name']} ({error['letterboxd_dict']['Year']}): {error['error']}")
    print(f"{len(watchlist_error)} watchlist errors")
    for error in watchlist_error:
        print(f"\t{error['letterboxd_dict']['Name']} ({error['letterboxd_dict']['Year']}): {error['error']}")


if __name__ == '__main__':
    main()
