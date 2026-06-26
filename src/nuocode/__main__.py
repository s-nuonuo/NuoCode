import sys

from nuocode.cli import main

if __name__ == "__main__":
    # chap15: --team-member 自治循环入口（T29）
    if len(sys.argv) > 1 and sys.argv[1] == "--team-member":
        from nuocode.cli.team_member import main_team_member
        main_team_member()
    else:
        main()
