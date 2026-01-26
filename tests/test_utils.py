import unittest
import sys
from pathlib import Path

# Add the parent directory to the path so we can import utils.py
sys.path.append(str(Path(__file__).parent.parent))

from utils import sanitize_filename

class TestFilenameSanitization(unittest.TestCase):

    def test_standard_title(self):
        """Test a normal title without spaces or special characters."""
        self.assertEqual(sanitize_filename("Saintess"), "Saintess")

    def test_spaces_to_underscores(self):
        """Test that spaces are converted to underscores."""
        self.assertEqual(sanitize_filename("Villainous Saintess"), "Villainous_Saintess")
        self.assertEqual(sanitize_filename(" The Saintess "), "_The_Saintess_")

    def test_illegal_characters_removed(self):
        """Test that Windows/Linux illegal characters are stripped."""
        # Tests removal of: ? * : " < > | / \
        self.assertEqual(sanitize_filename("Is it wrong?"), "Is_it_wrong")
        self.assertEqual(sanitize_filename("Star*Wars: A New Hope"), "StarWars_A_New_Hope")
        self.assertEqual(sanitize_filename("My/Novel\\Path|Name<Tag>"), "MyNovelPathNameTag")
        self.assertEqual(sanitize_filename('Title with "Quotes"'), "Title_with_Quotes")

    def test_complex_combination(self):
        """Test a complex title with spaces, punctuation, and illegal characters."""
        input_title = "Villainous Saintess: Vol 1? (Updated)"
        expected = "Villainous_Saintess_Vol_1_(Updated)"
        self.assertEqual(sanitize_filename(input_title), expected)

if __name__ == '__main__':
    unittest.main()
