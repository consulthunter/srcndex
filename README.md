# Mimir

Mimir is a data extractor for git (primarily GitHub) repositories.

Mimir looks through all the code (currently only Java) files. It extracts information
on the code files such as packages, classes, annotations, methods, etc.

After it extracts this information using `tree-sitter` it leverages `PyDriller` to extract
git information for the code files, iterating over every commit for the project. Mimir also extracts
project documentation putting the documentation in a vector database, `Chroma`.

Finally, Mimir saves the extracted code data in a SQLite `code_data.db` and the extracted documentation
in a `docs` folder as `chroma.sqlite3`. All under the project's name in the `output` directory.

## Installation

Dependencies:
- `python 3.13+`
- `git`

Clone the repository:

`git clone https://github.com/consulthunter/mimir`

Create a python 3.13+ virtual environment:

`python -m venv venv`

Activate the virtual environment and install the requirements:
- Windows
  - CMD
    - `venv\Scripts\activate.bat`
  - Powershell
    - `venv\Scripts\activate.ps1`
- Linux
  - `source venv/bin/activate`

`pip install -r requirements.txt`

Create the config:

`python run_create_default_config.py`

Run the example:

`python run_collect`

Check the `/output/` directory for the `code_data.db` and the `docs.db` under the project's name.

