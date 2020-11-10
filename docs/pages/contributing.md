Thanks for considering making a contribution to the Allzpark project!

The goal of Allzpark is making film and games productions more fun to work on, for artists and developers alike. Almost every company with any experience working in this field has felt the pain of managing software and versions when all you really want to do is make great pictures. Allzpark can really help with that, and you can really help Allzpark!

<br>

### Quickstart

Allzpark works out of the Git repository.

```bash
git clone https://github.com/mottosso/allzpark.git
cd allzpark
python -m allzpark --demo
```

Get the up-to-date requirements by having a copy of Allzpark already installed.

- See [Quickstart](/quickstart) for details

<br>

### Architecture

The front-end is written in Python and [Qt.py](https://github.com/mottosso/Qt.py), and the back-end is [bleeding-rez](https://github.com/mottosso/bleeding-rez). You are welcome to contribute to either of these projects.

Graphically, the interface is written in standard Qt idioms, like MVC to separate between logic and visuals. The window itself is an instance of `QMainWindow`, whereby each "tab" is a regular `QDockWidget`, which is how you can move them around and dock them freely.

- [model.py](https://github.com/mottosso/allzpark/blob/master/allzpark/model.py)
- [view.py](https://github.com/mottosso/allzpark/blob/master/allzpark/view.py)
- [control.py](https://github.com/mottosso/allzpark/blob/master/allzpark/control.py)

User preferences is stored in a `QSettings` object, including window layout. See `view.py:Window.closeEvent()` for how that works.

<br>

### Development

To make changes and/or contribute to Allzpark, here's how to run it from its Git repository.

```bash
git clone https://github.com/mottosso/allzpark.git
cd allzpark
python -m allzpark
```

From here, Python picks up the `allzpark` package from the current working directory, and everything is set to go. For use with Rez, try this.

```bash
# powershell
git clone https://github.com/mottosso/allzpark.git
cd allzpark
. env.ps1
> python -m allzpark
```

This will ensure a reproducible environment via Rez packages.

<br>

### Versioning

You typically won't have to manually increment the version of this project.

Instead, you can find the current version based on the current commit.

```bash
python -m allzpark --version
1.3.5
```

This is the version to be used when making a new GitHub release, and the version used by setup.py during release on PyPI (in case you should accidentally tag your GitHub release errouneously).

Major and minor versions are incremented for breaking and new changes respectively, the patch version however is special. It is incremented automatically in correspondance with the current commit number. E.g. commit number 200 yields a patch number of 200. See `allzpark/version.py` for details.

To see the patch version as you develop, ensure `git` is available on PATH, as it is used to detect the commit number at launch. Once built and distributed to PyPI, this number is then embedded into the resulting package. See `setup.py` for details.

<br>

### Resources

The current icon set is from [Haiku](https://github.com/darealshinji/haiku-icons).

<br>

### Guidelines

There are a few ways you can contribute to this project.

1. Use it and report any issues [here](https://github.com/mottosso/allzpark/issues)
1. Submit ideas for improvements or new features [here](https://github.com/mottosso/allzpark/issues)
1. Add or improve [this documentation](https://github.com/mottosso/allzpark/tree/master/docs)
1. Help write tests to avoid regressions and help future contributors spot mistakes

Any other thoughts on how you would like to contribute? [Let me know](https://github.com/mottosso/allzpark/issues).

<br>

### Documentation

The documentation you are reading right now is hosted in the Allzpark git repository on GitHub, and built with a static site-generator called [mkdocs](https://www.mkdocs.org/) along with a theme called [mkdocs-material](https://squidfunk.github.io/mkdocs-material/).

Mkdocs can host the entirety of the website on your local machine, and automatically update whenever you make changes to the Markdown documents. Here's how you can get started.

<div class="tabs">
  <button class="tab powershell " onclick="setTab(event, 'powershell')"><p>powershell</p><div class="tab-gap"></div></button>
  <button class="tab bash " onclick="setTab(event, 'bash')"><p>bash</p><div class="tab-gap"></div></button>
</div>

<div class="tab-content powershell" markdown="1">

You can either use Rez and Pipz.

```powershell
cd allzpark\docs
rez env pipz -- install -r requirements.txt
. serve.ps1
```

Or install dependencies into your system-wide Python.

```powershell
cd allzpark\docs
pip install -r requirements.txt
mkdocs serve
```

</div>

<div class="tab-content bash" markdown="1">

```bash
cd allzpark/docs
rez env pipz -- install -r requirements.txt
rez env git python mkdocs_material-4.4.0 mkdocs_git_revision_date_plugin==0.1.5 -- mkdocs serve
```

Or install dependencies into your system-wide Python.

```powershell
cd allzpark/docs
pip install -r requirements.txt
mkdocs serve
```

</div>

You should see a message about how to browse to the locally hosted documentation in your console.

<br>

#### Guidelines

Things to keep in mind as you contribute to the documentation

- **Windows-first** Allzpark is for all platforms, but Windows-users are typically less tech-savvy than Linux and MacOS users and the documentation should reflect that.
- **Try-catch** When documenting a series of steps to accomplish a task, start with the minimal ideal case, and then "catch" potential errors afterwards. This helps keep the documentation from branching out too far, and facilitates a cursory skimming of the documentation. See [quickstart](/quickstart) for an example.
