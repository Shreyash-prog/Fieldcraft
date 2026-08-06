from textkit.slug import slugify
def test_basic(): assert slugify("Hello World") == "hello-world"
def test_punct(): assert slugify("Foo!!Bar") == "foo-bar"
def test_trim(): assert slugify("--Trim--") == "trim"
def test_collapse(): assert slugify("A   B") == "a-b"
