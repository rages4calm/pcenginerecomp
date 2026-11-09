# Selecting useful compatibility inputs

Popularity is useful for choosing relevant ports; hardware diversity is more
useful for discovering toolkit defects. This is a proposed test matrix, not a
compatibility list or a promise that any title completes. Game-specific recipes,
patches and addresses belong in consumers, never in the shared runtime/compiler.

| Input | Why it is useful | First bounded qualification |
| --- | --- | --- |
| Bomberman '94, PC Engine HuCard | Five-player battle mode broadens input/multitap testing | Cold startup, single-player input, then independent multi-port control |
| Castlevania: Rondo of Blood, original PC Engine Super CD | A different loader/content structure from the existing CD regression; voices, cutscenes and branching action | Native cold boot/file creation/introduction now qualified; playable action and audio remain separate gates |
| Street Fighter II: Champion Edition, PC Engine | Explicit large-ROM mapper and six-button input | Preserve the existing mapper/full-source identity tests; compare contributor routes separately |
| Soldier Blade, original HuCard | Shooter scrolling, sprite activity and a repeatable scoring route | Fixed startup/input window and native/reference parity before longer routes |
| Populous, PC Engine HuCard | Dedicated cartridge RAM board rather than ordinary ROM mapping | Explicit populous profile, cartridge-RAM reads/writes and native source isolation |
| Ginga Fukei Densetsu Sapphire, Arcade CD | Arcade Card expansion and different CD activity | Separate expansion profile; do not infer support from a successful ordinary CD boot |

Start with Bomberman and Rondo alongside the existing HuCard/CD inputs. Populous
is the next especially useful board-specific addition. Sapphire is a later
expansion qualification; extra titles are not prerequisites for current compiler
work. SuperGrafx-only Dai Makaimura would test a different hardware profile and
should wait for an explicit dual-VDC/VPC implementation, rather than being treated
as an ordinary PC Engine game.

Konami's [official lineup descriptions](https://www.konami.com/games/pcemini/lineup/jp/en/)
identify Bomberman's five-player mode and Rondo's voices/cutscenes. MAME's
[HuCard list](https://github.com/mamedev/mame/blob/master/hash/pce.xml) identifies
the Populous board; its [CD list](https://github.com/mamedev/mame/blob/master/hash/pcecd.xml)
identifies Sapphire's Arcade Card requirement, while
[SuperGrafx inputs](https://github.com/mamedev/mame/blob/master/hash/sgx.xml)
are listed separately. These are selection references, not evidence from this runtime.

Retain exact original input hashes/profile/region and independent reference/build
identities in private receipts. Distinguish interpreter startup, compiled membership,
actually executed native instructions and gameplay. A genre or visible effect
suggests a test target; it does not establish a particular undocumented bus trick.
Public fixtures remain authored and contain no retail assets or captured code.
