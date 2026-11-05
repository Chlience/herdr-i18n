# herdr-i18n

[简体中文](README.md)

[Herdr's desktop app](https://github.com/herdrdev/herdr-app) is English-only, and upstream asks that interface features be built as layouts and mods. This repository turns translation catalogs into complete layouts in other languages: apart from the text, the window has the same structure, look and behavior as Herdr's own `main` layout.

| Language | Folder | Herdr version | Coverage |
|---|---|---|---|
| Simplified Chinese | [`zh-cn/`](zh-cn/) | v0.1.13 | 100% |

## Install

Update Herdr to the version above (Settings › Updates) and open it at least once.

```sh
git clone https://github.com/Chlience/herdr-i18n && cd herdr-i18n
python3 tools/i18n.py install zh-CN --keys
herdr-app do layout.switch '{"name":"zh-cn"}'
```

`install` writes only that language's `zh-cn-*` mods and `layouts/zh-cn.json`. It stops rather than replace a file of the same name it didn't generate.

`--keys` adds a `layout:zh-cn` section to `keys.json`, so the Settings, palette, Keys and picker shortcuts open the translated screens. The section applies only while the layout shows, but Herdr then treats `keys.json` as yours and stops adding new default shortcuts to it. Without `--keys`, screens opened by clicking are translated and screens opened by shortcut are in English.

You can also ask an agent in Herdr: have it read `~/.config/herdr-app/AGENTS.md`, then add this repository's `zh-cn/` folder.

**Update:** after Herdr updates, `git pull` and run `install` again. An older build usually keeps working but misses the new version's fixes and features.

**Uninstall:** switch to another layout with `layout.switch`, then delete `layouts/zh-cn.json`, `mods/zh-cn-*` and the `layout:zh-cn` section of `keys.json`.

## Limits

- Only Herdr's `main` layout is translated; the Terminals and Herdr 98 layouts stay in English.
- Screens the app opens by itself stay in English: Welcome on first start, What's new after an update, and Settings when opened from an update notice.
- Text the app draws itself stays in English: notifications, native menus and some errors. The body of What's new comes from the release notes, also in English.
- The action column in Keys shows command names, such as `space select 1`. They are built from command IDs, so a catalog can't translate them.
- Each build holds copies of Herdr's mods, so a new Herdr release needs a new build here to carry upstream's fixes.

## Add a language

You only need Python 3, with no packages to install. The tool downloads the herdr-app source pinned in `upstream.json`.

```sh
python3 tools/i18n.py new ja --name 日本語 --title "Herdr 日本語"
# translate the empty strings in locales/ja.json; empty ones show in English
python3 tools/i18n.py check ja -v       # coverage, stale entries and errors
python3 tools/i18n.py build ja          # writes ja/
python3 tools/i18n.py install ja --keys --home ~/.config/herdr-app
```

A catalog has three tables:

- `literals`: plain strings, keyed by the English text.
- `templates`: template strings. You can reorder the `${...}` and translate the text inside them, but not change the code, or `check` fails. So a catalog is only data, and reviewing a pull request never means reviewing code.
- `per_file`: a different translation for one file, keyed like `help/main.js`. `null` keeps the English there. Words like `open` are ids in other files, so the template from `new` lists them only here; don't move them to `literals`.

Strings the code compares (as in `action === "open"`) are never translated, and `build` lists them.

`source/strings.json` lists every text to translate, with its file and line. In your pull request, commit the generated folder too, and look at the result in Herdr: longer text can break a layout.

If the tool misses a text or picks up something that isn't one, edit `source/rules.json`: `ignore` drops strings people don't read, `include` adds ones it missed.

## Move to a new Herdr release

```sh
python3 tools/i18n.py upgrade v0.1.14   # pins it, and lists changed texts and each language's coverage
# add translations; build fails outright if a patch in upstream.json stopped matching
python3 tools/i18n.py build
python3 -m unittest discover -s tools   # includes a test that builds change only text
```

Also review `screens` in `upstream.json` (each screen's size in upstream's `src/window.rs`) and the mod lists. GitHub Actions checks for a new release daily and opens an issue with a report of what changed.

## License

Apache-2.0, as herdr-app. The mods in each language folder are modified herdr-app files; the first line of each names its source.
