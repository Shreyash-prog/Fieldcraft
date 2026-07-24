from slugify import slugify
def test_basic(): assert slugify("Hello World") == "hello-world"
def test_trim_spaces(): assert slugify("  Spaces  ") == "spaces"
def test_punctuation(): assert slugify("Foo!!Bar") == "foo-bar"
def test_collapse(): assert slugify("Multiple   Spaces") == "multiple-spaces"
def test_trim_hyphens(): assert slugify("--Trim--") == "trim"
def test_existing(): assert slugify("Already-Slug") == "already-slug"
