"""game_name.py unit tests (stdlib unittest, no pytest needed).

Run:  python -m unittest discover -s scripts -p "test_*.py" -v

All CJK / fullwidth literals are written as \\u escapes on purpose so the file
stays pure-ASCII and cannot be corrupted by console codepage issues on Windows.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from game_name import (  # noqa: E402
    MAX_NAME_LENGTH,
    MIN_ALIAS_LENGTH,
    NON_GAME_KEYWORDS,
    NON_GAME_NAMES,
    derive_game_name,
    looks_like_game,
    normalize_game_name,
)

LQ = "\u300a"        # left double angle bracket
RQ = "\u300b"        # right double angle bracket
LB = "\u3010"        # left black lenticular bracket
RB = "\u3011"        # right black lenticular bracket
FULL_COLON = "\uff1a"
GENSHIN = "\u539f\u795e"                                  # a real game name
NEWS_TAG = "\u6e38\u620f\u65b0\u95fb"                     # blacklisted channel
HEIHUA = "\u9ed1\u795e\u8bdd" + FULL_COLON + "\u949f\u9997"
HEIHUA_HALF = "\u9ed1\u795e\u8bdd:\u949f\u9997"

# non-game tags that used to leak through the exact-equality blacklist
ACCELERATOR = "\u8fc5\u6e38\u7f51\u6e38\u52a0\u901f\u5668"   # a game accelerator
EA_FULL = "EA \u7535\u5b50\u827a\u754c"                      # EA with CN name
NS_CONSOLE = "\u4efb\u5929\u5802Switch\u4e3b\u673a"          # Switch console
TGA_CEREMONY = "TGA\u9881\u5956\u5178\u793c"                 # award ceremony
GAME_TALK = "\u6e38\u620f\u6742\u8c08"                       # column name
CAPCOM = "\u5361\u666e\u7a7a"
KOJIMA = "\u5c0f\u5c9b\u79c0\u592b"
DISNEY = "\u8fea\u58eb\u5c3c"
COMIC = "\u6f2b\u753b"
BILIBILI = "B\u7ad9"
NINTENDO = "\u4efb\u5929\u5802"

# real game names that embed a vendor / media word and must NOT be blocked
MVC = "\u6f2b\u753b\u82f1\u96c4VS" + CAPCOM                  # Marvel vs Capcom
DISNEY_GAME = DISNEY + "\u68a6\u5e7b\u661f\u8c37"            # Disney Dreamlight
SMASH = NINTENDO + "\u660e\u661f\u5927\u4e71\u6597"          # Smash Bros

# slash cases
POKEMON_PAIR = "\u5b9d\u53ef\u68a6" + FULL_COLON + "\u98ce/\u6ce2"
POKEMON_PAIR_HALF = "\u5b9d\u53ef\u68a6:\u98ce/\u6ce2"
GTA_ALIAS = "GTA6/\u4fa0\u76d7\u730e\u8f666"



def quoted(name):
    return LQ + name + RQ


def bracketed(name):
    return LB + name + RB


class TestNormalizeGameName(unittest.TestCase):
    def test_empty_inputs(self):
        self.assertEqual(normalize_game_name(""), "")
        self.assertEqual(normalize_game_name(None), "")

    def test_strips_outer_whitespace(self):
        self.assertEqual(normalize_game_name("  " + GENSHIN + " \t"), GENSHIN)

    def test_halfwidth_colon_becomes_fullwidth(self):
        self.assertEqual(normalize_game_name(HEIHUA_HALF), HEIHUA)
        self.assertEqual(normalize_game_name(HEIHUA), HEIHUA)

    def test_collapses_inner_whitespace(self):
        self.assertEqual(normalize_game_name("Epic   Games"), "Epic Games")
        self.assertEqual(normalize_game_name("Half\n\nLife"), "Half Life")

    def test_slash_alias_is_truncated(self):
        self.assertEqual(normalize_game_name("GTA6/Grand Theft Auto VI"), "GTA6")
        self.assertEqual(normalize_game_name("Fate/Grand Order"), "Fate")
        self.assertEqual(normalize_game_name(GTA_ALIAS), "GTA6")

    def test_slash_kept_when_one_side_is_too_short(self):
        # both sides must look like a standalone alias, otherwise the slash
        # belongs to the name itself
        self.assertEqual(normalize_game_name(POKEMON_PAIR), POKEMON_PAIR)
        self.assertEqual(normalize_game_name(POKEMON_PAIR_HALF), POKEMON_PAIR)
        self.assertEqual(normalize_game_name("A/B"), "A/B")
        self.assertEqual(normalize_game_name("Portal/2"), "Portal/2")

    def test_slash_length_boundary(self):
        short = "A" * (MIN_ALIAS_LENGTH - 1)
        ok = "A" * MIN_ALIAS_LENGTH
        self.assertEqual(normalize_game_name(ok + "/" + ok), ok)
        self.assertEqual(
            normalize_game_name(ok + "/" + short), ok + "/" + short
        )
        self.assertEqual(
            normalize_game_name(short + "/" + ok), short + "/" + ok
        )

    def test_double_colon_is_kept(self):
        self.assertEqual(
            normalize_game_name("A PLATiNA :: LAB"), "A PLATiNA :: LAB"
        )
        cjk_double = GENSHIN + "::" + GENSHIN
        self.assertEqual(normalize_game_name(cjk_double), cjk_double)

    def test_latin_only_name_keeps_halfwidth_colon(self):
        latin = "TIC-TAC: Twelve o'clock"
        self.assertEqual(normalize_game_name(latin), latin)

    def test_no_space_after_fullwidth_colon(self):
        heihua_spaced = "\u9ed1\u795e\u8bdd: \u949f\u9997"
        self.assertEqual(normalize_game_name(heihua_spaced), HEIHUA)
        self.assertEqual(
            normalize_game_name("\u9ed1\u795e\u8bdd " + FULL_COLON + " \u949f\u9997"),
            HEIHUA,
        )



class TestLooksLikeGame(unittest.TestCase):
    def test_plain_name_passes(self):
        self.assertTrue(looks_like_game(GENSHIN))
        self.assertTrue(looks_like_game("Hollow Knight"))

    def test_empty_fails(self):
        self.assertFalse(looks_like_game(""))
        self.assertFalse(looks_like_game("   "))
        self.assertFalse(looks_like_game(None))

    def test_blacklist_entries_all_rejected(self):
        for banned in NON_GAME_NAMES:
            self.assertFalse(looks_like_game(banned), banned)

    def test_blacklist_is_case_and_space_insensitive(self):
        self.assertFalse(looks_like_game("steam"))
        self.assertFalse(looks_like_game("STEAM"))
        self.assertFalse(looks_like_game("  Steam  "))
        self.assertFalse(looks_like_game("Epic   Games"))

    def test_overlong_name_rejected(self):
        self.assertTrue(looks_like_game("A" * MAX_NAME_LENGTH))
        self.assertFalse(looks_like_game("A" * (MAX_NAME_LENGTH + 1)))

    def test_keyword_entries_all_rejected(self):
        for keyword in NON_GAME_KEYWORDS:
            self.assertFalse(looks_like_game(keyword), keyword)

    def test_suffixed_non_game_tags_rejected(self):
        # these all leaked through the old exact-equality blacklist
        for tag in (
            ACCELERATOR,
            EA_FULL,
            NS_CONSOLE,
            TGA_CEREMONY,
            GAME_TALK,
            "PS5",
            "Xbox Series X",
            BILIBILI,
            CAPCOM,
            KOJIMA,
            DISNEY,
            COMIC,
        ):
            self.assertFalse(looks_like_game(tag), tag)

    def test_real_games_embedding_vendor_words_pass(self):
        # containment matching must not over-block real game names
        for name in ("EA SPORTS FC", MVC, DISNEY_GAME, SMASH):
            self.assertTrue(looks_like_game(name), name)



class TestDeriveFromTitle(unittest.TestCase):
    def test_double_angle_quotes(self):
        self.assertEqual(
            derive_game_name("PV" + quoted(GENSHIN) + "released"), GENSHIN
        )

    def test_lenticular_brackets(self):
        self.assertEqual(
            derive_game_name(bracketed(GENSHIN) + "big update"), GENSHIN
        )

    def test_first_of_multiple_same_kind_wins(self):
        title = quoted("A") + "vs" + quoted("B")
        self.assertEqual(derive_game_name(title), "A")

    def test_first_of_multiple_mixed_kind_wins(self):
        self.assertEqual(derive_game_name(quoted("A") + bracketed("B")), "A")
        self.assertEqual(derive_game_name(bracketed("B") + quoted("A")), "B")

    def test_unpaired_brackets_do_not_match(self):
        self.assertEqual(derive_game_name(LQ + "A" + RB), "")
        self.assertEqual(derive_game_name(LB + "A" + RQ), "")
        self.assertEqual(derive_game_name("no bracket at all"), "")

    def test_empty_bracket_pair_does_not_match(self):
        self.assertEqual(derive_game_name(LQ + RQ), "")
        self.assertEqual(derive_game_name(LB + RB), "")

    def test_length_boundary(self):
        ok = "A" * MAX_NAME_LENGTH
        too_long = "A" * (MAX_NAME_LENGTH + 1)
        self.assertEqual(derive_game_name(quoted(ok)), ok)
        self.assertEqual(derive_game_name(quoted(too_long)), "")

    def test_extracted_name_is_normalized(self):
        self.assertEqual(derive_game_name(quoted(HEIHUA_HALF)), HEIHUA)
        self.assertEqual(derive_game_name(quoted(" " + GENSHIN + " ")), GENSHIN)

    def test_missing_or_none_title(self):
        self.assertEqual(derive_game_name(None), "")
        self.assertEqual(derive_game_name(""), "")


class TestDeriveWithTagFallback(unittest.TestCase):
    def test_title_wins_over_tag(self):
        self.assertEqual(derive_game_name(quoted(GENSHIN), "Steam"), GENSHIN)
        self.assertEqual(derive_game_name(quoted(GENSHIN), NEWS_TAG), GENSHIN)
        self.assertEqual(derive_game_name(quoted("A"), "B"), "A")

    def test_clean_tag_used_when_title_has_no_bracket(self):
        self.assertEqual(derive_game_name("plain title", GENSHIN), GENSHIN)

    def test_blacklisted_tag_rejected(self):
        self.assertEqual(derive_game_name("plain title", NEWS_TAG), "")
        self.assertEqual(derive_game_name("plain title", "Steam"), "")
        self.assertEqual(derive_game_name("plain title", "Epic Games"), "")
        self.assertEqual(derive_game_name("plain title", ACCELERATOR), "")
        self.assertEqual(derive_game_name("plain title", NS_CONSOLE), "")
        self.assertEqual(derive_game_name("plain title", TGA_CEREMONY), "")

    def test_real_game_tag_with_vendor_word_adopted(self):
        self.assertEqual(derive_game_name("plain title", DISNEY_GAME), DISNEY_GAME)
        self.assertEqual(derive_game_name("plain title", "EA SPORTS FC"), "EA SPORTS FC")


    def test_overlong_tag_rejected(self):
        self.assertEqual(
            derive_game_name("plain title", "A" * (MAX_NAME_LENGTH + 1)), ""
        )

    def test_tag_is_normalized_when_adopted(self):
        self.assertEqual(derive_game_name("plain title", HEIHUA_HALF), HEIHUA)

    def test_idempotent_when_previous_value_is_fed_back_as_tag(self):
        title = "PV" + quoted(GENSHIN)
        first = derive_game_name(title, "")
        self.assertEqual(derive_game_name(title, first), first)
        plain = "plain title"
        second = derive_game_name(plain, GENSHIN)
        self.assertEqual(derive_game_name(plain, second), second)


if __name__ == "__main__":
    unittest.main(verbosity=2)
