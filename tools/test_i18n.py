"""Run with: python3 -m unittest discover -s tools"""
import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import i18n  # noqa: E402
import jslex  # noqa: E402

REPO = i18n.ROOT


def strings(src):
    return [src[t.start:t.end] for t in jslex.tokenize(src) if t.kind == 'string']


class Lexer(unittest.TestCase):
    def test_quote_in_regex_does_not_pair_with_strings(self):
        src = 'const a = /^x \\("[^"]+"\\)$/.test(m ?? ""); el.child("Spaces");'
        self.assertEqual(strings(src), ['""', '"Spaces"'])

    def test_slash_in_character_class_does_not_end_regex(self):
        self.assertEqual(strings('p.split(/[/"]/); f("a");'), ['"a"'])

    def test_division_is_not_a_regex(self):
        self.assertEqual(strings('x = a / b; y("t"); z = (c) / 2; w("u");'), ['"t"', '"u"'])

    def test_quote_in_comments_is_ignored(self):
        self.assertEqual(strings('// it\'s "here\n/* don\'t */ f("a");'), ['"a"'])

    def test_template_nests_strings_and_templates(self):
        src = '`a ${x ? `b ${y}` : "c"} d`'
        (t,) = jslex.tokenize(src)
        self.assertEqual((t.kind, t.end), ('template', len(src)))
        self.assertEqual([c.kind for c in t.children], ['template', 'string'])

    def test_braces_in_template_holes(self):
        (t,) = jslex.tokenize('`${{ a: "}" }.a}`')
        self.assertEqual(len(t.holes), 1)

    def test_string_value(self):
        for literal, value in [(r'"a\u2026"', 'a…'), (r'"\u{1F600}"', '😀'), (r'"\ud83d\ude00"', '😀'),
                               (r'"\x41"', 'A'), (r'"it\'s"', "it's"), (r'"\n"', '\n'), (r"'\"'", '"')]:
            self.assertEqual(jslex.string_value(literal), value)

    def test_holes_allow_text_and_order_to_change(self):
        before = 'A ${x} ${y ? `to ${z}` : "none"}'
        after = '${y ? `至 ${z}` : "无"} 甲 ${x}'
        self.assertEqual(jslex.holes(before), jslex.holes(after))

    def test_holes_catch_changed_code(self):
        for after in ['A ${evil()} ${y ? `to ${z}` : "none"}',
                      'A ${x} ${y ? `to ${evil()}` : "none"}',
                      'A ${x} ${y ? `to ${z}` : "none" + evil()}']:
            self.assertNotEqual(jslex.holes('A ${x} ${y ? `to ${z}` : "none"}'), jslex.holes(after))

    def test_holes_reject_leaving_the_template(self):
        with self.assertRaises(jslex.LexError):
            jslex.holes('a` + evil() + `b')


CATALOG = {'locale': 'xx', 'name': 'X', 'title': 'Herdr X',
           'literals': {'Save': 'Sauver', 'Quote': 'say "hi"', 'Empty': ''},
           'templates': {'Hi ${name}': 'Salut ${name}'},
           'per_file': {'a/main.js': {'Save': None}}}


class Translate(unittest.TestCase):
    def run_it(self, src, file='b/main.js'):
        risky = []
        out, _ = i18n.translate(src, i18n.lookup(CATALOG, file), risky)
        return out, risky

    def test_literal_is_encoded_safely(self):
        self.assertEqual(self.run_it('f("Quote");')[0], 'f("say \\"hi\\"");')

    def test_escaped_source_text_matches(self):
        self.assertEqual(self.run_it(r'f("\u0053ave");')[0], 'f("Sauver");')

    def test_empty_translation_keeps_english(self):
        self.assertEqual(self.run_it('f("Empty");')[0], 'f("Empty");')

    def test_per_file_null_keeps_english(self):
        self.assertEqual(self.run_it('f("Save");', 'a/main.js')[0], 'f("Save");')

    def test_template_and_nested_text(self):
        self.assertEqual(self.run_it('f(`Hi ${name}`, `${x ? "Save" : y}`);')[0],
                         'f(`Salut ${name}`, `${x ? "Sauver" : y}`);')

    def test_only_the_import_of_herdr_moves(self):
        out = self.run_it('import { run } from "herdr"; f("herdr");')[0]
        self.assertEqual(out, 'import { run } from "../api.js"; f("herdr");')

    def test_compared_text_stays_and_is_reported(self):
        out, risky = self.run_it('if (a === "Save" || "Save" !== b) f(x ? "Save" : y); switch (c) { case "Save": }')
        self.assertEqual(out, 'if (a === "Save" || "Save" !== b) f(x ? "Sauver" : y); switch (c) { case "Save": }')
        self.assertEqual(risky, ['Save', 'Save', 'Save'])

    def test_only_text_changes(self):
        src = 'const a = /"/.test(b) ? "Save" : `Hi ${name}`; // "Save"\n'
        self.assertEqual(jslex.skeleton(src), jslex.skeleton(self.run_it(src)[0]))

    def test_problems(self):
        bad = {**CATALOG, 'templates': {'Hi ${name}': 'Salut ${evil()}'}}
        self.assertTrue(i18n.problems(bad))
        bad = {**CATALOG, 'templates': {'Hi ${name}': 'x` + evil() + `'}}
        self.assertTrue(i18n.problems(bad))
        self.assertEqual(i18n.problems(CATALOG), [])


class Keys(unittest.TestCase):
    CFG = {'mods': ['picker'], 'frames': ['settings'], 'keys': {'app.settings': 'settings'}}

    def test_keys(self):
        bindings = {'a': 'app.settings', 'b': 'mod.open:picker', 'c': 'tab.new', 'd': 'mod.open:other',
                    'e': 'app.settings:updates', 'f': {'command': 'app.settings'},
                    'g': {'command': 'app.settings', 'args': {'section': 'look'}},
                    'h': {'command': 'mod.open', 'args': {'name': 'picker'}}}
        self.assertEqual(i18n.keys_section(bindings, 'xx-', self.CFG), {
            'a': 'mod.open:xx-settings', 'b': 'mod.open:xx-picker',
            'f': 'mod.open:xx-settings', 'h': 'mod.open:xx-picker'})


class Repo(unittest.TestCase):
    """A whole repository with a tiny herdr-app, built and installed."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.saved = i18n.ROOT, i18n.LOCALES, i18n.SOURCE
        self.addCleanup(lambda: (setattr(i18n, 'ROOT', self.saved[0]), setattr(i18n, 'LOCALES', self.saved[1]),
                                 setattr(i18n, 'SOURCE', self.saved[2])))
        root = self.tmp / 'repo'
        (root / 'tools').mkdir(parents=True)
        (root / 'source').mkdir()
        (root / 'locales').mkdir()
        shutil.copy(REPO / 'tools' / 'shim.js', root / 'tools')
        shutil.copy(REPO / 'tools' / 'RECIPE.md', root / 'tools')
        i18n.ROOT, i18n.LOCALES, i18n.SOURCE = root, root / 'locales', root / 'source'
        i18n.write_json(root / 'upstream.json', {
            'repository': 'x/y', 'tag': 'v1', 'commit': 'abc', 'mods': ['menu'], 'frames': ['settings'],
            'screens': {'settings': {'kind': 'dialog'}}, 'keys': {'app.settings': 'settings'},
            'patches': [{'file': 'settings/main.js', 'find': 'const LOOKS = {',
                         'replace': 'const SHOWN = {locale};\nconst LOOKS = { "{layout}": {title},'}]})
        i18n.write_json(root / 'source' / 'rules.json', {'ignore': ['Skip me', 'Herdr', 'Herdr i18n'], 'include': [
            {'file': 'menu/main.js', 'text': 'open'}]})
        self.up = self.tmp / 'up'
        for rel, text in {
            'defaults/mods/menu/main.js': 'import { run } from "herdr";\nf("Save", "Skip me", `Hi ${name}`, "open");\n',
            'defaults/mods/menu/mod.json': '{ "place": "left", "title": "Unread title" }',
            'defaults/frame/settings/main.js': 'const LOOKS = { main: "Herdr" };\nf("New words here");\n',
            'defaults/frame/settings/mod.json': '{ "place": "none" }',
            'defaults/layouts/main.json': '{"id": "root", "children": [{"content": {"mod": "menu"}}, {"content": {"mod": "other"}}]}',
            'defaults/keys.json': '{"global": {"ctrl-,": "app.settings", "ctrl-t": "tab.new"}}',
            'defaults/keys.macos.json': '{"global": {"cmd-,": "app.settings"}}',
        }.items():
            (self.up / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.up / rel).write_text(text)
        i18n.write_json(root / 'locales' / 'xx.json', CATALOG)
        self.args = argparse.Namespace(upstream=str(self.up), locales=[], verbose=False, strict=False)
        i18n.extract(self.args)
        i18n.build(self.args)
        self.root = root
        self.home = self.tmp / 'home'
        (self.home / 'layouts').mkdir(parents=True)
        (self.home / 'mods').mkdir()

    def install(self, locale=None, keys=False):
        i18n.install(argparse.Namespace(locale=locale, home=str(self.home), keys=keys))

    def old_build(self, code='zz'):
        """What an earlier version installed: one layout and set of mods per language."""
        (self.home / 'layouts' / f'{code}.json').write_text(json.dumps({'terminal_menu': f'{code}-menu'}))
        for name in ('menu', 'tabs'):
            (self.home / 'mods' / f'{code}-{name}').mkdir()
            (self.home / 'mods' / f'{code}-{name}' / 'main.js').write_text(f'{i18n.MARK} from herdr-app v0 x ({code}).\n')

    def test_extract_lists_text_and_skips_rules(self):
        data = json.loads((i18n.SOURCE / 'strings.json').read_text())
        self.assertEqual(set(data['literals']), {'Save', 'New words here', 'open'})
        self.assertEqual(set(data['templates']), {'Hi ${name}'})
        self.assertEqual(data['per_file'], {'menu/main.js': ['open']})

    def test_every_language_has_its_own_copy(self):
        mod = self.root / 'mods' / 'i18n-menu'
        english, french = (mod / 'en' / 'main.js').read_text(), (mod / 'xx' / 'main.js').read_text()
        self.assertTrue(french.startswith(i18n.MARK))
        self.assertIn('from "../api.js"', french)
        self.assertIn('f("Sauver", "Skip me", `Salut ${name}`, "open")', french)
        self.assertIn('f("Save", "Skip me", `Hi ${name}`, "open")', english)
        self.assertIn('from "../api.js"', english)

    def test_main_names_the_language(self):
        main = (self.root / 'mods' / 'i18n-menu' / 'main.js').read_text()
        self.assertTrue(main.startswith(i18n.MARK))
        self.assertIn('export { default } from "./en/main.js";', main)

    def test_patches_know_their_language(self):
        settings = self.root / 'mods' / 'i18n-settings'
        self.assertIn('const SHOWN = "xx";\nconst LOOKS = { "herdr-i18n": "Herdr X", main: "Herdr" }', (settings / 'xx' / 'main.js').read_text())
        self.assertIn('const SHOWN = "en";\nconst LOOKS = { "herdr-i18n": "Herdr i18n", main: "Herdr" }', (settings / 'en' / 'main.js').read_text())

    def test_mod_json_and_shim(self):
        self.assertEqual(json.loads((self.root / 'mods' / 'i18n-menu' / 'mod.json').read_text()),
                         {'place': 'none', 'title': 'Unread title'})
        self.assertEqual(json.loads((self.root / 'mods' / 'i18n-settings' / 'mod.json').read_text())['overlay'], {'kind': 'dialog'})
        shim = (self.root / 'mods' / 'i18n-menu' / 'api.js').read_text()
        self.assertIn('[["en", "English"], ["xx", "X"]]', shim)
        self.assertNotIn('__CONFIG__', shim)

    def test_one_layout_and_its_keys(self):
        self.assertEqual([p.name for p in (self.root / 'layouts').iterdir()], ['herdr-i18n.json'])
        tree = json.loads((self.root / 'layouts' / 'herdr-i18n.json').read_text())
        self.assertEqual([c['content']['mod'] for c in tree['children']], ['i18n-menu', 'other'])
        self.assertEqual(tree['terminal_menu'], 'i18n-menu')
        self.assertEqual(json.loads((self.root / 'keys.json').read_text()),
                         {'layout:herdr-i18n': {'ctrl-,': 'mod.open:i18n-settings'}})

    def test_patch_that_stopped_matching_fails_the_build(self):
        (self.up / 'defaults/frame/settings/main.js').write_text('const OTHER = {};')
        with self.assertRaises(SystemExit):
            i18n.build(self.args)

    def test_broken_catalog_fails_before_touching_the_build(self):
        catalog = json.loads((i18n.LOCALES / 'xx.json').read_text())
        catalog['templates']['Hi ${name}'] = 'Salut ${evil()}'
        i18n.write_json(i18n.LOCALES / 'xx.json', catalog)
        with self.assertRaises(SystemExit):
            i18n.build(self.args)
        self.assertTrue((self.root / 'mods' / 'i18n-menu' / 'main.js').exists())

    def test_check_reports_coverage(self):
        self.args.strict = True
        with self.assertRaises(SystemExit):
            i18n.check(self.args)  # "New words here" is missing
        catalog = json.loads((i18n.LOCALES / 'xx.json').read_text())
        catalog['literals']['New words here'] = 'Mots'
        catalog['per_file'] = {'menu/main.js': {'open': 'ouvert'}}
        del catalog['literals']['Quote'], catalog['literals']['Empty']
        i18n.write_json(i18n.LOCALES / 'xx.json', catalog)
        i18n.check(self.args)

    def test_new_locale_starts_empty_and_joins_the_menu(self):
        i18n.new(argparse.Namespace(locale='fr', name='Français', title='Herdr Français'))
        catalog = json.loads((i18n.LOCALES / 'fr.json').read_text())
        self.assertEqual(catalog['literals']['Save'], '')
        self.assertNotIn('open', catalog['literals'])  # an id elsewhere: only ever per file
        self.assertEqual(catalog['per_file'], {'menu/main.js': {'open': ''}})
        i18n.build(self.args)
        mod = self.root / 'mods' / 'i18n-menu'
        # Untranslated stays English, even the per-file words.
        self.assertIn('f("Save", "Skip me", `Hi ${name}`, "open")', (mod / 'fr' / 'main.js').read_text())
        self.assertIn('["fr", "Français"]', (mod / 'api.js').read_text())

    def test_english_is_built_in(self):
        with self.assertRaises(SystemExit):
            i18n.new(argparse.Namespace(locale='en', name='English', title='x'))

    def test_bad_locale_names_are_refused(self):
        for name in ('tools', '../x'):
            with self.assertRaises(SystemExit):
                i18n.catalogs([name])

    def test_install_defaults_to_english_then_keeps_the_choice(self):
        self.install()
        main = self.home / 'mods' / 'i18n-menu' / 'main.js'
        self.assertIn('"./en/main.js"', main.read_text())
        self.install('xx')
        self.assertIn('"./xx/main.js"', main.read_text())
        self.install()
        self.assertIn('"./xx/main.js"', main.read_text())
        self.assertTrue((self.home / 'layouts' / 'herdr-i18n.json').exists())

    def test_install_refuses_an_unknown_language(self):
        with self.assertRaises(SystemExit):
            self.install('qq')

    def test_install_removes_mods_a_later_build_dropped(self):
        self.install()
        (self.home / 'mods' / 'i18n-old').mkdir()
        (self.home / 'mods' / 'i18n-old' / 'main.js').write_text(i18n.MAIN.replace('{code}', 'en'))
        self.install()
        self.assertEqual(sorted(p.name for p in (self.home / 'mods').iterdir()), ['i18n-menu', 'i18n-settings'])

    def test_install_replaces_an_earlier_per_language_build(self):
        self.old_build()
        i18n.write_json(self.home / 'keys.json', {'global': {}, 'layout:zz': {'a': 'b'}})
        self.install('xx', keys=True)
        self.assertFalse((self.home / 'layouts' / 'zz.json').exists())
        self.assertFalse((self.home / 'mods' / 'zz-menu').exists())
        self.assertFalse((self.home / 'mods' / 'zz-tabs').exists())
        self.assertNotIn('layout:zz', json.loads((self.home / 'keys.json').read_text()))

    def test_install_leaves_other_layouts_and_mods_alone(self):
        (self.home / 'layouts' / 'mine.json').write_text(json.dumps({'terminal_menu': 'mine-menu'}))
        for name, first in [('i18n-mine', '// my own mod\n'), ('mine-menu', '// my own mod\n'), ('mine-tabs', '// mine\n')]:
            (self.home / 'mods' / name).mkdir()
            (self.home / 'mods' / name / 'main.js').write_text(first)
        self.install()
        self.assertTrue((self.home / 'mods' / 'i18n-mine').exists())
        self.assertTrue((self.home / 'mods' / 'mine-menu').exists())
        self.assertTrue((self.home / 'layouts' / 'mine.json').exists())

    def test_install_refuses_to_replace_what_it_did_not_write(self):
        (self.home / 'mods' / 'i18n-menu').mkdir()
        (self.home / 'mods' / 'i18n-menu' / 'main.js').write_text('// my own mod\n')
        with self.assertRaises(SystemExit):
            self.install()
        self.assertEqual((self.home / 'mods' / 'i18n-menu' / 'main.js').read_text(), '// my own mod\n')
        shutil.rmtree(self.home / 'mods' / 'i18n-menu')
        layout = self.home / 'layouts' / 'herdr-i18n.json'
        layout.write_text('{"terminal_menu": "something-else"}')
        with self.assertRaises(SystemExit) as refused:
            self.install()
        self.assertIn('.old', str(refused.exception))
        self.assertEqual(layout.read_text(), '{"terminal_menu": "something-else"}')

    def test_install_keys_follow_the_persons_own_bindings(self):
        i18n.write_json(self.home / 'keys.json', {'global': {'alt-s': 'app.settings', 'ctrl-t': 'tab.new'}})
        self.install(keys=True)
        keys = json.loads((self.home / 'keys.json').read_text())
        self.assertEqual(keys['layout:herdr-i18n'], {'alt-s': 'mod.open:i18n-settings'})
        self.assertEqual(keys['global']['ctrl-t'], 'tab.new')


class Shipped(unittest.TestCase):
    """The committed build, against the pinned herdr-app when it's in .cache/."""

    def test_every_language_changes_only_text(self):
        cfg = i18n.config()
        up = REPO / '.cache' / f"herdr-app-{cfg['tag']}"
        if not up.exists():
            self.skipTest('run i18n.py fetch first')
        everyone = [(i18n.ENGLISH[0], i18n.ENGLISH[2])] + [(c, cat['title']) for c, cat in i18n.catalogs([])]
        for code, title in everyone:
            for name, folder, scripts in i18n.sources(up):
                for script in scripts:
                    file = f'{name}/{script.name}'
                    built = (REPO / 'mods' / f'{i18n.PREFIX}{name}' / code / script.name).read_text()
                    self.assertTrue(built.startswith(i18n.MARK))
                    original = i18n.apply_patches(script.read_text(), file, cfg, title, code)
                    self.assertEqual(jslex.skeleton(built), jslex.skeleton(original), f'{code} {file}')


if __name__ == '__main__':
    unittest.main()
