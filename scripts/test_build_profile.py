"""Profile generation, privacy and offline-build regressions (no network)."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import build_profile as profile


class ProfileTests(unittest.TestCase):
    def test_generated_profile_keeps_proof_and_private_projects_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'scripts').mkdir()
            template = profile.ROOT / 'scripts' / 'README.template.md'
            (root / 'scripts' / template.name).write_text(template.read_text(encoding='utf-8'), encoding='utf-8')
            measurer = Mock()
            measurer.width.return_value = (70, 70)
            measurer.ref.return_value = 70
            measurer.fits.return_value = True
            with patch.object(profile, 'ROOT', root), patch.object(profile, 'ASSETS', root / 'assets'), \
                 patch.object(profile, 'Measurer', return_value=measurer), patch.object(profile, 'refresh_repos'):
                profile.main()
                self.assertEqual(profile.check(), 0)
            readme = (root / 'README.md').read_text(encoding='utf-8')
            self.assertNotIn('@@', readme)
            self.assertTrue(readme.startswith('<p align="center"><picture>'))
            self.assertNotIn('# Arya Mahindrakar', readme)
            self.assertLess(readme.index('assets/hero-light.svg'), readme.index('assets/cta-email-light.svg'))
            self.assertLess(readme.index('assets/cta-repos-light.svg'), readme.index('## [AutoSWE]'))
            self.assertIn('AI Engineer, LLM Agents, Cloud', readme)
            self.assertIn('Eval regression gates in CI', readme)
            self.assertLess(readme.index('## [AutoSWE]'), readme.index('## Beyond the flagship'))
            for slug in ('AI-Agent', 'mcp-agent'):
                self.assertIn(f'**{slug} (private):**', readme)
                self.assertNotIn(f'github.com/Arya-9989/{slug}', readme)
            self.assertLess(readme.index('[Momentum]'), readme.index('## Education & Certification'))
            self.assertLess(readme.index('## Education & Certification'), readme.index('<details>'))
            self.assertIn('B.Tech, Cloud Technology & Information Security', readme)
            self.assertIn('Ajeenkya D Y Patil University, Pune · 2022 – 2026', readme)
            self.assertIn('Cloud Computing · Network Security · Information Security · Operating Systems · DBMS · Software Engineering · Data Structures & Algorithms', readme)
            self.assertIn('AWS Certified Cloud Practitioner', readme)
            self.assertIn('Amazon Web Services · Apr 2026 – Apr 2029', readme)
            self.assertIn('EC2 · S3 · IAM · VPC networking · security groups · load balancing · cloud deployment best practices', readme)
            self.assertIn('Pune, India', readme)
            for excluded in ('Analytics Engine', 'Ransomware Detection', 'Evidence Archiving', '100%', '10+ hours', '20 min'):
                self.assertNotIn(excluded, readme)
            self.assertIn('Grafana monitoring with threshold-based alerting', readme)
            self.assertIn('Wazuh SIEM file-integrity and unauthorized-access monitoring', readme)
            self.assertIn('Grafana · Wazuh SIEM', readme)
            self.assertIn('**Quantum-Resistant Cloud Encryption** — IEEE-style research paper on post-quantum cryptography for cloud data', readme)
            self.assertIn('**Cooling Solutions for Data Centers** — IEEE-style research paper', readme)
            self.assertLess(readme.index('## Education & Certification'), readme.index('## Research'))
            self.assertLess(readme.index('## Research'), readme.index('<details>'))
            monitoring = readme.split('### Infrastructure Observability & SIEM Platform')[1].split('## Education')[0]
            self.assertNotIn('https://', monitoring)
            self.assertEqual(len(list((root / 'assets').glob('*.svg'))), 8)

    def test_live_metadata_cannot_replace_reviewed_claims(self):
        repo = dict(slug='public-project', desc='Reviewed proof', lang='Python')
        live = Mock(returncode=0, stdout='{"description":"Unverified numbers", "primaryLanguage":{"name":"Go"}}')
        with patch.object(profile, 'REPOS', [repo]), patch.object(profile.subprocess, 'run', return_value=live):
            profile.refresh_repos()
        self.assertEqual(repo['desc'], 'Reviewed proof')
        self.assertEqual(repo['lang'], 'Go')

    def test_missing_font_fails_without_contacting_a_cdn(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(profile, 'CACHE', Path(tmp)), \
             patch.object(profile.urllib.request, 'urlopen') as network:
            with self.assertRaisesRegex(RuntimeError, 'does not download fonts'):
                profile.font_file('https://cdn.example/font.woff2')
            network.assert_not_called()


if __name__ == '__main__':
    unittest.main()
