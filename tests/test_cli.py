from __future__ import annotations

from main import build_parser


def test_parser_requires_company_name() -> None:
    parser = build_parser()
    args = parser.parse_args(["示例科技", "--funding-round", "A轮", "--bp-file", "a.pdf", "--bp-file", "b.docx"])
    assert args.company_name == "示例科技"
    assert args.funding_round == "A轮"
    assert args.bp_files == ["a.pdf", "b.docx"]
    assert args.auto_select_competitors is False
    assert args.max_competitors == 5


def test_parser_auto_select_competitors_flag() -> None:
    parser = build_parser()
    args = parser.parse_args(["示例科技", "--auto-select-competitors", "--max-competitors", "3"])
    assert args.auto_select_competitors is True
    assert args.max_competitors == 3
