import copy
import io
import json
import subprocess
import unittest
from unittest.mock import patch

from scripts import build_profile as profile


class RefreshReposTests(unittest.TestCase):
    def test_online_metadata_preserves_all_curated_copy(self):
        for transport in ('cli', 'api'):
            with self.subTest(transport=transport):
                repo = copy.deepcopy(profile.REPOS[1])
                curated = copy.deepcopy(repo)
                cli = {'description': 'Uncurated GitHub description',
                       'primaryLanguage': {'name': 'Go'},
                       'highlights': 'Uncurated highlights', 'proof': 'Uncurated proof'}
                api = {**cli, 'language': 'Go'}
                result = subprocess.CompletedProcess([], 0 if transport == 'cli' else 1,
                                                     stdout=json.dumps(cli))
                with patch.object(profile, 'REPOS', [repo]), \
                     patch.object(profile.subprocess, 'run', return_value=result), \
                     patch.object(profile.urllib.request, 'urlopen',
                                  return_value=io.BytesIO(json.dumps(api).encode())):
                    profile.refresh_repos()
                self.assertEqual(repo, {**curated, 'lang': 'Go'})

    def test_offline_keeps_curated_copy_and_python_label(self):
        repo = copy.deepcopy(profile.REPOS[1])
        stored = copy.deepcopy(repo)
        with patch.object(profile, 'REPOS', [repo]), \
             patch.object(profile.subprocess, 'run', side_effect=OSError('offline')), \
             patch.object(profile.urllib.request, 'urlopen', side_effect=OSError('offline')):
            profile.refresh_repos()
        self.assertEqual(repo, stored)
        self.assertEqual(repo['lang'], 'Python')

    def test_missing_live_language_keeps_stored_label(self):
        for language in (None, {}, {'name': None}):
            with self.subTest(language=language):
                repos = copy.deepcopy(profile.REPOS)
                stored = copy.deepcopy(repos)
                result = subprocess.CompletedProcess([], 0, stdout=json.dumps(
                    {'description': 'Uncurated description', 'primaryLanguage': language}))
                with patch.object(profile, 'REPOS', repos), \
                     patch.object(profile.subprocess, 'run', return_value=result):
                    profile.refresh_repos()
                self.assertEqual(repos, stored)


if __name__ == '__main__':
    unittest.main()
