from browserrig.observation.delta import INTRO, delta, unmarked

HEADER = "# Form\nurl: https://example.org/form\ntab: T1\ncursor: x=1 y=2 (viewport CSS pixels)"
BASE = f"""{HEADER}

in viewport:
  [HEADER]
    [1] link "Home" -> /
  [MAIN]
    <form "Order">
      [2] textbox "Name"
      [3] textbox "Email"
    [4] button "Help\""""


def test_changed_lines_keep_their_section_and_group_lines():
    current = BASE.replace(
        '[3] textbox "Email"', '[3] textbox "Email" value="a@b.c" focused'
    )
    assert delta(BASE, current).split("\n") == [
        *HEADER.split("\n"),
        "",
        INTRO,
        "  [MAIN]",
        '    <form "Order">',
        '-     [3] textbox "Email"',
        '+     [3] textbox "Email" value="a@b.c" focused',
    ]


def test_element_after_a_group_is_not_placed_inside_it():
    current = BASE.replace('[4] button "Help"', '[4] button "Help" expanded')
    assert delta(BASE, current).split("\n")[-3:] == [
        "  [MAIN]",
        '-   [4] button "Help"',
        '+   [4] button "Help" expanded',
    ]


def test_removed_section_and_unchanged_body():
    current = BASE.replace('  [HEADER]\n    [1] link "Home" -> /\n', "")
    assert delta(BASE, current).split("\n")[-2:] == [
        "- [HEADER]",
        '-   [1] link "Home" -> /',
    ]
    assert delta(BASE, BASE).endswith(INTRO + "\n  (no changes)")


def test_new_marks_are_dropped_before_comparing():
    marked = BASE.replace('    [4] button "Help"', '    *[4] button "Help"').replace(
        '[1] link "Home"', '## *[1] link "Home"'
    )
    assert unmarked(marked) == BASE.replace('[1] link "Home"', '## [1] link "Home"')
