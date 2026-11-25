from typing import assert_type

from lib_harness import Box, make_box

assert_type(make_box(), Box[int])
assert_type(make_box().get(), int)
