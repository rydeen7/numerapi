# -*- coding: utf-8 -*-

# System
import zipfile
import json
import os
from datetime import datetime, timedelta
import getpass
import errno
import logging

# Third Party
import requests
import numpy as np


API_TOURNAMENT_URL = 'https://api-tournament.numer.ai'


class NumerAPI(object):

    """Wrapper around the Numerai API"""

    def __init__(self, public_id=None, secret_key=None, verbosity="INFO"):
        """
        initialize Numerai API wrapper for Python

        verbosity: indicates what level of messages should be displayed
            valid values: "debug", "info", "warning", "error", "critical"
        """
        if public_id and secret_key:
            self.token = (public_id, secret_key)
        elif not public_id and not secret_key:
            self.token = None
        else:
            print("You need to supply both a public id and a secret key.")
            self.token = None

        self.logger = logging.getLogger(__name__)

        # set up logging
        numeric_log_level = getattr(logging, verbosity.upper())
        if not isinstance(numeric_log_level, int):
            raise ValueError('invalid verbosity: %s' % verbosity)
        log_format = "%(asctime)s %(levelname)s %(name)s: %(message)s"
        logging.basicConfig(format=log_format, level=numeric_log_level)
        self.submission_id = None

    def _unzip_file(self, src_path, dest_path, filename):
        """unzips file located at src_path into destination_path"""
        self.logger.info("unzipping file...")

        # construct full path (including file name) for unzipping
        unzip_path = "{0}/{1}".format(dest_path, filename)

        # create parent directory for unzipped data
        try:
            os.makedirs(unzip_path)
        except OSError as exception:
            if exception.errno != errno.EEXIST:
                raise

        # extract data
        with zipfile.ZipFile(src_path, "r") as z:
            z.extractall(unzip_path)

        return True

    def download_current_dataset(self, dest_path=".", unzip=True):
        """download dataset for current round

        dest_path: desired location of dataset file
        unzip: indicates whether to unzip dataset
        """
        self.logger.info("downloading current dataset...")

        # set up download path
        now = datetime.now().strftime("%Y%m%d")
        dataset_name = "numerai_dataset_{0}".format(now)
        file_name = "{0}.zip".format(dataset_name)
        dataset_path = "{0}/{1}".format(dest_path, file_name)

        # get data for current dataset
        url = 'https://api.numer.ai/competitions/current/dataset'
        dataset_res = requests.get(url, stream=True)
        dataset_res.raise_for_status()

        # create parent folder if necessary
        try:
            os.makedirs(dest_path)
        except OSError as exception:
            if exception.errno != errno.EEXIST:
                raise

        # write dataset to file
        with open(dataset_path, "wb") as f:
            for chunk in dataset_res.iter_content(1024):
                f.write(chunk)

        # unzip dataset
        if unzip:
            self._unzip_file(dataset_path, dest_path, dataset_name)

        return True

    def _call(self, query, variables=None, authorization=False):
        body = {'query': query,
                'variables': variables}
        headers = {'Content-type': 'application/json',
                   'Accept': 'application/json'}
        if authorization and self.token:
            public_id, secret_key = self.token
            headers['Authorization'] = \
                'Token {}${}'.format(public_id, secret_key)
        r = requests.post(API_TOURNAMENT_URL, json=body, headers=headers)
        return r.json()

    def get_competitions(self, round_num=None):
        """ get information about round

        round_num: the requests round, defaults to all rounds
        """
        self.logger.info("getting rounds...")

        if round_num is None:
            query_rounds = "rounds"
        else:
            query_rounds = "rounds(number: {})".format(round_num)
        query = '''
            query simpleRoundsRequest {{
              {} {{
                number
                resolveTime
                datasetId
                openTime
                resolvedGeneral
                resolvedStaking
              }}
            }}
        '''.format(query_rounds)
        result = self._call(query)
        return result

    def submission_status(self):
        """display submission status"""
        if self.submission_id is None:
            raise ValueError('`submission_id` cannot be None')

        query = '''
            query submissions($submission_id: String!) {
              submissions(id: $submission_id) {
                originality {
                  pending
                  value
                }
                concordance {
                  pending
                  value
                }
                consistency
                validation_logloss
              }
            }
            '''
        variable = {'submission_id': self.submission_id}
        status_raw = self._call(query, variable, authorization=True)
        status_raw = status_raw['data']['submissions'][0]
        status = {}
        for key, value in status_raw.items():
            if isinstance(value, dict):
                value = value['value']
            status[key] = value
        return status

    def upload_predictions(self, file_path):
        """uploads predictions from file"""
        self.logger.info("uploading prediction...")

        auth_query = \
            '''
            query($filename: String!) {
                submission_upload_auth(filename: $filename) {
                    filename
                    url
                }
            }
            '''
        variable = {'filename': os.path.basename(file_path)}
        submission_resp = self._call(auth_query, variable, authorization=True)
        submission_auth = submission_resp['data']['submission_upload_auth']
        file_object = open(file_path, 'rb').read()
        requests.put(submission_auth['url'], data=file_object)
        create_query = \
            '''
            mutation($filename: String!) {
                create_submission(filename: $filename) {
                    id
                }
            }
            '''
        variables = {'filename': submission_auth['filename']}
        create = self._call(create_query, variables, authorization=True)
        self.submission_id = create['data']['create_submission']['id']
        return self.submission_id
