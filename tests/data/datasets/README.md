# Test datasests directory

This directory is intended for inclusion of DataLad subdatasets (git submodules)
for testing purposes.
It is excluded from sdist and wheel packages.

To add a subdataset (git submodule):

```
datalad install -d . -s $PUBLIC_REMOTE tests/data/$DIR
```
