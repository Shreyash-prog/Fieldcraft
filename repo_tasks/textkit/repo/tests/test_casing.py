from textkit.casing import to_snake, to_camel
def test_snake_camel(): assert to_snake("CamelCase") == "camel_case"
def test_snake_kebab(): assert to_snake("kebab-case") == "kebab_case"
def test_camel_snake(): assert to_camel("snake_case") == "snakeCase"
def test_camel_kebab(): assert to_camel("kebab-case") == "kebabCase"
