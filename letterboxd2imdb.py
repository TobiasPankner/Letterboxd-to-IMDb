import argparse
import concurrent.futures
import hashlib
import json
import os
import requests
from argparse import ArgumentParser
import csv
import re
import time
from zipfile import ZipFile
from io import TextIOWrapper
from tqdm import tqdm

imdb_cookie = ""


class RateLimitError(Exception):
    pass


def files_hash(files):
    block_size = 65536
    hasher = hashlib.md5()
    for file in files:
        with open(file, 'rb') as afile:
            buf = afile.read(block_size)
            while len(buf) > 0:
                hasher.update(buf)
                buf = afile.read(block_size)
    return hasher.hexdigest()


def dict_hash(dictionary):
    dhash = hashlib.md5()
    encoded = json.dumps(dictionary, sort_keys=True).encode()
    dhash.update(encoded)
    return dhash.hexdigest()


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
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Accept": "text/html",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
        "Cache-Control": "max-age=0",
    }

    resp = requests.get(letterboxd_uri, headers=headers)
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

    resp = requests.post("https://api.graphql.imdb.com/",
                         json=req_body, headers=headers)

    if resp.status_code != 200:
        if resp.status_code == 429:
            raise RateLimitError("IMDb Rate limit exceeded")
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

    resp = requests.put(
        f"https://www.imdb.com/watchlist/{imdb_id}", headers=headers)

    if resp.status_code != 200:
        if resp.status_code == 429:
            raise RateLimitError("IMDb Rate limit exceeded")
        raise ValueError(
            f"Error adding to IMDb watchlist. Code: {resp.status_code}")

    if resp.status_code == 403:
        print(f"Failed to authenticate with cookie")
        exit(1)


def create_imdb_list(list_name, description=""):
    """Create a new IMDb list and return the list ID"""
    req_body = {
        "query": "mutation CreateList($input: CreateListInput!) { createList(input: $input) { listId __typename } }",
        "operationName": "CreateList",
        "variables": {
            "input": {
                "name": list_name,
                "listDescription": description,
                "allowDuplicates": False,
                "listType": "TITLES",
                "visibility": "PRIVATE"
            }
        }
    }

    headers = {
        "content-type": "application/json",
        "cookie": imdb_cookie,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    }

    resp = requests.post("https://api.graphql.imdb.com/",
                         json=req_body, headers=headers)
    if resp.status_code == 200:
        json_resp = resp.json()

        if 'errors' in json_resp and len(json_resp['errors']) > 0:
            print(f"GraphQL errors: {json_resp['errors']}")
            raise ValueError(
                f"Failed to create IMDb list: {json_resp['errors'][0]['message']}")

        if 'data' in json_resp and json_resp['data'] and 'createList' in json_resp['data']:
            list_id = json_resp['data']['createList']['listId']
            return list_id
    elif resp.status_code == 429:
        raise RateLimitError("IMDb Rate limit exceeded")
    else:
        print(f"HTTP error {resp.status_code}: {resp.text}")
        raise ValueError(
            f"Failed to create IMDb list: HTTP {resp.status_code}")

    raise ValueError("Failed to create IMDb list")


def add_to_imdb_list(imdb_id, list_id):
    """Add a movie to an existing IMDb list"""
    req_body = {
        "query": "mutation AddItemToList($input: AddItemToListInput!) { addItemToList(input: $input) { listId __typename } }",
        "operationName": "AddItemToList",
        "variables": {
            "input": {
                "listId": list_id,
                "item": {
                    "itemElementId": imdb_id
                }
            }
        }
    }
    headers = {
        "content-type": "application/json",
        "cookie": imdb_cookie,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    }
    resp = requests.post("https://api.graphql.imdb.com/",
                         json=req_body, headers=headers)

    if resp.status_code != 200:
        if resp.status_code == 429:
            raise RateLimitError("IMDb Rate limit exceeded")
        print(
            f"Failed to add to list: HTTP {resp.status_code}, Response: {resp.text}")
        raise ValueError(
            f"Error adding to IMDb list. Code: {resp.status_code}")

    json_resp = resp.json()
    if 'errors' in json_resp and len(json_resp['errors']) > 0:
        first_error_msg = json_resp['errors'][0]['message']
        print(f"GraphQL error adding to list: {first_error_msg}")
        if 'Authentication' in first_error_msg:
            print(f"Failed to authenticate with cookie")
            exit(1)
        else:
            raise ValueError(first_error_msg)


def get_user_lists_from_profile():
    """Get user lists by parsing the main IMDb profile page"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cookie": imdb_cookie,
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1"
    }

    # Try to access the main IMDb page first to see if we're logged in
    url = "https://www.imdb.com/profile"
    user_id = None

    try:
        resp = requests.get(url, headers=headers, timeout=10)

        if resp.status_code == 200:
            content = resp.text

            # Look for user ID pattern in the HTML
            matches = re.findall(r'/user/(ur\d+)/', content)
            if matches:
                user_id = matches[0]

            # Also look for any list references in the main page
            pattern = r'href="/list/(ls\d+)"[^>]*>([^<]+)</a>'
            lists_dict = {}
            matches = re.findall(pattern, content, re.IGNORECASE)
            for match in matches:
                list_id, list_name = match
                clean_name = list_name.strip()
                clean_name = re.sub(r'&[a-zA-Z0-9#]+;', '', clean_name)
                clean_name = re.sub(r'\s+', ' ', clean_name).strip()

                if clean_name and list_id.startswith('ls'):
                    lists_dict[clean_name] = list_id

            if lists_dict:
                return lists_dict

    except Exception as e:
        pass

    # If we found a user ID, try to access their lists page directly
    if user_id:
        list_urls = [
            f"https://www.imdb.com/user/{user_id}/lists/",
            f"https://www.imdb.com/user/{user_id}/",
        ]

        for url in list_urls:
            try:
                resp = requests.get(url, headers=headers, timeout=10)

                if resp.status_code == 200:
                    content = resp.text

                    # Look for lists using the working pattern
                    pattern = r'href="/list/(ls\d+)/?[^"]*"[^>]*>([^<]+)</a>'
                    lists_dict = {}

                    try:
                        matches = re.findall(pattern, content, re.IGNORECASE)

                        for match in matches:
                            list_id, list_name = match

                            # Clean up the list name
                            clean_name = list_name.strip()
                            clean_name = re.sub(
                                r'&[a-zA-Z0-9#]+;', '', clean_name)
                            clean_name = re.sub(
                                r'\s+', ' ', clean_name).strip()
                            # Remove HTML tags
                            clean_name = re.sub(r'<[^>]+>', '', clean_name)

                            if clean_name and list_id and list_id.startswith('ls') and len(list_id) > 2:
                                lists_dict[clean_name] = list_id

                    except Exception as e:
                        pass

                    if lists_dict:
                        return lists_dict

            except Exception as e:
                continue

    return {}


def find_or_create_imdb_list(list_name, description=""):
    """Find an existing list by name or create a new one if it doesn't exist"""
    try:
        existing_lists = get_user_lists_from_profile()

        if existing_lists:
            # Check if our target list exists
            if list_name in existing_lists:
                list_id = existing_lists[list_name]
                return list_id

            # Check for similar named lists (case insensitive, partial match)
            similar_lists = []
            for existing_name in existing_lists.keys():
                if (list_name.lower() in existing_name.lower() or
                        existing_name.lower() in list_name.lower()):
                    similar_lists.append(
                        (existing_name, existing_lists[existing_name]))

    except Exception as e:
        pass

    # If no existing list found, create a new one
    try:
        list_id = create_imdb_list(list_name, description)
        return list_id

    except Exception:
        raise


def rate_letterboxd_to_imdb(letterboxd_dict):
    imdb_id = get_imdb_id(letterboxd_dict['Letterboxd URI'])
    if imdb_id is None:
        raise ValueError("Cannot find IMDb title")

    if letterboxd_dict['Action'] == "rate":
        rate_on_imdb(imdb_id, int(float(letterboxd_dict['Rating']) * 2))
    elif letterboxd_dict['Action'] == "watchlist":
        add_to_imdb_watchlist(imdb_id)
    elif letterboxd_dict['Action'] == "add_to_list":
        add_to_imdb_list(imdb_id, letterboxd_dict['ListId'])

    return letterboxd_dict


def main():
    global imdb_cookie

    parser = ArgumentParser(
        description="Imports your Letterboxd ratings and watchlist into IMDb. Can also create custom lists for unrated movies.")
    optional = parser._action_groups.pop()
    required = parser.add_argument_group('required arguments')
    parser.add_argument_group('optional arguments')
    required.add_argument("-f", dest="zipfile", type=str, required=True,
                          help="The exported zip file from letterboxd")
    optional.add_argument("-p", dest="parallel", type=int, default=5,
                          help="Urls to be processed in parallel (valid: 1 to 20)")
    optional.add_argument("-c", dest="clean", action=argparse.BooleanOptionalAction,
                          help="Add this flag to disable the history")
    optional.add_argument("-r", dest="rating", type=int, default=0,
                          help="The rating to give watched but unrated movies. By default they are ignored (valid: 1 to 10)")
    optional.add_argument("-w", dest="watchlist", action=argparse.BooleanOptionalAction,
                          help="Add this flag to also transfer your watchlist")
    optional.add_argument("-l", dest="create_list", action=argparse.BooleanOptionalAction,
                          help="Create an IMDb list for watched but unrated movies instead of rating them")
    optional.add_argument("--list-name", dest="list_name", type=str, default="Watched on Letterboxd - Unrated",
                          help="Name for the IMDb list to create for unrated movies (default: 'Watched on Letterboxd - Unrated')")
    parser._action_groups.append(optional)

    args = parser.parse_args()

    # Validate mutually exclusive options
    if args.rating > 0 and args.create_list:
        parser.error(
            "Cannot use both -r/--rating and -l/--create-list options together. Choose one method for handling unrated movies.")

    print(r"""
  _        _   _           _                _   ___   ___ __  __ ___  _    
 | |   ___| |_| |_ ___ _ _| |__  _____ ____| | |_  ) |_ _|  \/  |   \| |__ 
 | |__/ -_)  _|  _/ -_) '_| '_ \/ _ \ \ / _` |  / /   | || |\/| | |) | '_ \
 |____\___|\__|\__\___|_| |_.__/\___/_\_\__,_| /___| |___|_|  |_|___/|_.__/
                                                                           
""")

    try:
        with open('cookie.txt', 'r', encoding='latin-1') as file:
            imdb_cookie = file.read().replace('\n', '').strip()
    except:
        print("Failed to read cookie.txt, have you created the file?")
        exit(1)

    current_files_hash = files_hash(['cookie.txt', args.zipfile])
    prev_hashes = set()
    if not args.clean:
        try:
            with open(f'history/{current_files_hash}.txt', 'r') as f:
                prev_hashes = set(f.read().strip().split("\n"))
        except Exception:
            pass

    ratings, watched_unfiltered, watchlist = read_zip(args.zipfile)

    to_transfer = []

    print(f"Letterboxd rated: {len(ratings)}")
    to_transfer.extend([dict(w, Action="rate") for w in ratings])

    # filter to get only the watched and unrated entries
    rating_uris = [rating['Letterboxd URI']
                   for rating in ratings if 'Letterboxd URI' in rating]
    watched = list(
        filter(lambda w: w['Letterboxd URI'] not in rating_uris, watched_unfiltered))

    print(f"Letterboxd watched (unrated): {len(watched)}")

    # Handle unrated watched movies
    if args.create_list and len(watched) > 0:
        # Find existing list or create new one
        try:
            list_id = find_or_create_imdb_list(
                args.list_name, "Movies watched on Letterboxd but not rated")
        except Exception as e:
            print(f"Failed to find or create IMDb list: {e}")
            print("Falling back to ignoring unrated movies")
            list_id = None

        if list_id:
            to_transfer.extend(
                [dict(w, Action="add_to_list", ListId=list_id) for w in watched])
        else:
            print("No list ID available, skipping unrated movies")
    elif args.create_list and len(watched) == 0:
        print("No unrated watched movies found to add to list")
    elif args.rating > 0:
        print(
            f"Letterboxd watched: {len(watched)} (will be rated {args.rating})")
        to_transfer.extend(
            [dict(w, Rating=args.rating / 2, Action="rate") for w in watched])
    else:
        print(
            f"Letterboxd watched: {len(watched)} (ignored, see -r or -l options)")

    print(
        f"Letterboxd watchlist: {len(watchlist)}{'' if args.watchlist else ' (ignored, see -w option)'}\n")
    if args.watchlist:
        to_transfer.extend([dict(w, Action="watchlist") for w in watchlist])

    to_transfer = list(filter(lambda d: dict_hash(d)
                       not in prev_hashes, to_transfer))

    success = []
    errors = []

    with tqdm(total=len(to_transfer), leave=False) as pbar:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as executor:
            future_to_url = {
                executor.submit(rate_letterboxd_to_imdb, letterboxd_dict): letterboxd_dict for letterboxd_dict in
                to_transfer
            }
            try:
                for future in concurrent.futures.as_completed(future_to_url):
                    letterboxd_dict = future_to_url[future]
                    pbar.update(1)
                    try:
                        success.append(future.result())
                    except RateLimitError:
                        print(
                            "\n\nIMDb rate limit exceeded, try again in a few minutes")
                        raise
                    except Exception as e:
                        errors.append(
                            {"letterboxd_dict": letterboxd_dict, "error": e})
            except KeyboardInterrupt:
                executor.shutdown(wait=True, cancel_futures=True)
            except RateLimitError:
                executor.shutdown(wait=True, cancel_futures=True)
                exit(1)
            finally:
                if not args.clean:
                    with open(f'history/{current_files_hash}.txt', 'a') as f:
                        f.write(
                            '\n' + '\n'.join([dict_hash(s) for s in success]))

    ratings_error = [
        e for e in errors if e['letterboxd_dict']['Action'] == 'rate']
    watchlist_error = [
        e for e in errors if e['letterboxd_dict']['Action'] == 'watchlist']
    list_error = [e for e in errors if e['letterboxd_dict']
                  ['Action'] == 'add_to_list']
    print(f"{len(ratings_error)} rating errors")
    for error in ratings_error:
        print(
            f"\t{error['letterboxd_dict']['Name']} ({error['letterboxd_dict']['Year']}): {error['error']}")
    print(f"{len(watchlist_error)} watchlist errors")
    for error in watchlist_error:
        print(
            f"\t{error['letterboxd_dict']['Name']} ({error['letterboxd_dict']['Year']}): {error['error']}")
    print(f"{len(list_error)} list errors")
    for error in list_error:
        print(
            f"\t{error['letterboxd_dict']['Name']} ({error['letterboxd_dict']['Year']}): {error['error']}")


if __name__ == '__main__':
    main()
