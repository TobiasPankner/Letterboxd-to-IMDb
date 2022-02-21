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

    return ratings, watched


def get_imdb_url(letterboxd_uri):
    resp = requests.get(letterboxd_uri)
    if resp.status_code != 200:
        return None

    # extract the IMDb url
    re_match = re.findall('href="(.+/maindetails)"', resp.text)
    if not re_match:
        return None

    return re_match[0]


def rate_on_imdb(imdb_url, rating):
    re_match = re.findall('title/(.+)/maindetails', imdb_url)
    if not re_match:
        return None

    imdb_id = re_match[0]
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
        raise ValueError(f"Error rating on IMDb {resp.status_code}")

    json_resp = resp.json()
    if 'errors' in json_resp and len(json_resp['errors']) > 0:
        first_error_msg = json_resp['errors'][0]['message']

        if 'Authentication' in first_error_msg:
            print(f"Failed to authenticate with cookie")
            exit(1)
        else:
            raise ValueError(first_error_msg)


def letterboxd_to_imdb(letterboxd_dict):
    imdb_url = get_imdb_url(letterboxd_dict['Letterboxd URI'])
    if imdb_url is None:
        raise ValueError("Cannot find IMDb title")
    rate_on_imdb(imdb_url, int(float(letterboxd_dict['Rating']) * 2))


def main():
    global imdb_cookie

    parser = ArgumentParser(description="Imports your Letterboxd ratings into IMDb")
    optional = parser._action_groups.pop()
    required = parser.add_argument_group('required arguments')
    parser.add_argument_group('optional arguments')
    required.add_argument("-f", dest="zipfile", type=str, required=True,
                          help="The exported zip file from letterboxd")
    optional.add_argument("-p", dest="parallel", type=int, default=5,
                          help="Urls to be processed in parallel (valid: 1 to 20)")
    optional.add_argument("-r", dest="rating", type=int, default=0,
                          help="The rating to give watched but unrated movies. By default they are ignored (valid: 1 to 10)")
    parser._action_groups.append(optional)

    args = parser.parse_args()

    print(r"""
      _        _   _           _                _   ___   ___ __  __ ___  ___ 
     | |   ___| |_| |_ ___ _ _| |__  _____ ____| | |_  ) |_ _|  \/  |   \| _ )
     | |__/ -_)  _|  _/ -_) '_| '_ \/ _ \ \ / _` |  / /   | || |\/| | |) | _ \
     |____\___|\__|\__\___|_| |_.__/\___/_\_\__,_| /___| |___|_|  |_|___/|___/

    """)

    try:
        with open('cookie.txt', 'r') as file:
            imdb_cookie = file.read().replace('\n', '').strip()
    except:
        print("Failed to read cookie.txt, have you created the file?")
        exit(1)

    ratings, watched_unfiltered = read_zip(args.zipfile)

    print(f"Rated Letterboxd entries: {len(ratings)}")

    # filter to get only the watched and unrated entries
    rating_uris = [rating['Letterboxd URI'] for rating in ratings]
    watched = list(filter(lambda w: w['Letterboxd URI'] not in rating_uris, watched_unfiltered))
    print(f"Watched Letterboxd entries: {len(watched)}{'' if args.rating > 0 else ' (ignored)'}\n")

    if args.rating > 0:
        ratings.extend([dict(w, Rating=args.rating / 2) for w in watched])

    success = []
    errors = []

    with tqdm(total=len(ratings)) as pbar:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as executor:
            future_to_url = {
                executor.submit(letterboxd_to_imdb, letterboxd_dict): letterboxd_dict for letterboxd_dict in ratings
            }
            for future in concurrent.futures.as_completed(future_to_url):
                letterboxd_dict = future_to_url[future]
                pbar.update(1)
                try:
                    success.append(future.result())
                except Exception as e:
                    errors.append({"letterboxd_dict": letterboxd_dict, "error": e})

    print(f"Successfully rated: {len(success)} ")
    print(f"{len(errors)} Errors")
    for error in errors:
        print(f"\t{error['letterboxd_dict']['Name']} ({error['letterboxd_dict']['Year']}): {error['error']}")


if __name__ == '__main__':
    main()
