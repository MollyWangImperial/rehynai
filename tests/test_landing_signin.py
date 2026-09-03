from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LandingSignInTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "index.html").read_text(encoding="utf-8")

    def test_sign_in_opens_a_modal_on_the_current_landing_page(self):
        self.assertIn('data-open-dialog="signin-dialog">Sign in</button>', self.source)
        self.assertIn('<dialog class="auth-dialog" id="signin-dialog"', self.source)
        self.assertNotIn('href="https://rehyn.onrender.com/sign-in?auth=signin"', self.source)

    def test_modal_contains_the_three_required_fields(self):
        self.assertIn('id="signin-name"', self.source)
        self.assertIn('id="signin-email"', self.source)
        self.assertIn('id="signin-trial-code"', self.source)
        self.assertIn("Enter your name, email, and trial code to continue.", self.source)

    def test_trial_code_is_sent_only_to_the_secure_handoff_endpoint(self):
        self.assertIn('https://rehyn.onrender.com/api/users/login-handoff', self.source)
        self.assertIn('trial_code: trialCode', self.source)
        self.assertIn('body.handoff_token', self.source)
        self.assertNotIn('test-trial-code', self.source)


if __name__ == "__main__":
    unittest.main()
