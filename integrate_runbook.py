content = open('D:/Technical Articles/failover-budget/failover_budget.py', encoding='utf-8').read()

old_parser = "    parser.add_argument('--max-seconds', type=float, default=MAX_SECONDS_DEFAULT,\n                        help='give up measuring after this long (default: 120)')\n"
new_parser = old_parser + "    parser.add_argument('--runbook', action='store_true',\n                        help='print the operator runbook with step-by-step commands')\n    parser.add_argument('--diagnose', action='store_true',\n                        help='print the diagnostic decision tree for a failing failover')\n"
assert old_parser in content, 'parser anchor not found'
content = content.replace(old_parser, new_parser)

marker = "    args = parser.parse_args(argv)\n"
assert marker in content, 'args anchor not found'
runbook_handler = marker + "    if args.runbook:\n        import runbook as _rb\n        _rb.render_runbook()\n        return 0\n    if args.diagnose:\n        import runbook as _rb\n        _rb.render_diagnose()\n        return 0\n"
content = content.replace(marker, runbook_handler)

open('D:/Technical Articles/failover-budget/failover_budget.py', 'w', encoding='utf-8').write(content)
print('Integrated runbook and diagnose flags')
