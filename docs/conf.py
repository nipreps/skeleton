import os
import sys

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.coverage',
    'sphinx.ext.doctest',
    "sphinx.ext.githubpages",
    'sphinx.ext.mathjax',
    'sphinx.ext.napoleon',
    "sphinx.ext.viewcode",
    "sphinxcontrib.apidoc",
    'sphinxarg.ext',  # argparse extension
    'nipype.sphinxext.plot_workflow',
]

project = 'PROJECT'
year_started = '2025'
org = 'nipreps'
author = 'The NiPreps Developers'
copyright = f'{year_started}-, {author}'

html_baseurl = os.environ.get('READTHEDOCS_CANONICAL_URL', '')
language = 'en'
master_doc = "index"
html_theme = "furo"
pygments_style = 'sphinx'
source_suffix = {
    '.rst': 'restructuredtext',
}
templates_path = ['_templates']
html_static_path = ["_static"]
html_js_files = [
]
html_css_files = [
]
todo_include_todos = False

exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

# Link dates and other references in the changelog
extensions += ['rst.linker']
link_files = {
    '../NEWS.rst': dict(
        using=dict(GH='https://github.com'),
        replace=[
            dict(
                pattern=r'(Issue #|\B#)(?P<issue>\d+)',
                url='{package_url}/issues/{issue}',
            ),
            dict(
                pattern=r'(?m:^((?P<scm_version>v?\d+(\.\d+){1,2}))\n[-=]+\n)',
                with_scm='{text}\n{rev[timestamp]:%d %b %Y}\n',
            ),
            dict(
                pattern=r'PEP[- ](?P<pep_number>\d+)',
                url='https://peps.python.org/pep-{pep_number:0>4}/',
            ),
        ],
    )
}

# Be strict about any broken references
nitpicky = True

# Include Python intersphinx mapping to prevent failures
# jaraco/skeleton#51
extensions += ['sphinx.ext.intersphinx']
intersphinx_mapping = {
    'python': ('https://docs.python.org/3/', None),
    'numpy': ('https://numpy.org/doc/stable/', None),
    'scipy': ('https://docs.scipy.org/doc/scipy/', None),
    'matplotlib': ('https://matplotlib.org/stable/', None),
    'bids': ('https://bids-standard.github.io/pybids/', None),
    'nibabel': ('https://nipy.org/nibabel/', None),
    'nipype': ('https://nipype.readthedocs.io/en/latest/', None),
    'niworkflows': ('https://www.nipreps.org/niworkflows/', None),
    'sdcflows': ('https://www.nipreps.org/sdcflows/', None),
    'smriprep': ('https://www.nipreps.org/smriprep/', None),
    'templateflow': ('https://www.templateflow.org/python-client', None),
    'tedana': ('https://tedana.readthedocs.io/en/latest/', None),
}

# Preserve authored syntax for defaults
autodoc_preserve_defaults = True
# These mocks may speed up module parsing, but might interfere with linking types
autodoc_mock_imports = [
    'numpy',
    'nitime',
    'matplotlib',
    'pandas',
    'nilearn',
    'seaborn',
]

extensions += ['sphinx.ext.napoleon']
napoleon_use_param = False
napoleon_custom_sections = [
    ('Inputs', 'params_style'),
    ('Outputs', 'returns_style'),
    ("Attributes", "Parameters"),
    ("Mandatory Inputs", "Parameters"),
    ("Optional Inputs", "Parameters"),
]
