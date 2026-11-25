from lib_harness import make_box

x: str = make_box().get()  # expect-error[reportAssignmentType, assignment]: int is not str
