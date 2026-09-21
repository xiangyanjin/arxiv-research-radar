# Install and use the Agent Skill

arXiv Research Radar ships as a complete skill folder: root-level `SKILL.md`, optional host UI metadata, a portable Python wrapper, and the application it operates. Describe your interests in natural language; the host agent configures a research profile and runs the deterministic retrieval and validation tools.

The skill uses the host's model for interpretation. It does not install a model SDK, require a retrieval API key, or create a paid model endpoint. Python 3.10+ on macOS or Linux is required; the current runtime uses `fcntl` and does not support Windows.

## Install the whole repository

For Codex, the documented user-level skill directory is `~/.agents/skills`. [Official skill documentation](https://learn.chatgpt.com/docs/build-skills)

```bash
mkdir -p ~/.agents/skills
git clone https://github.com/xiangyanjin/arxiv-research-radar.git ~/.agents/skills/arxiv-research-radar
```

If the destination exists, reuse that checkout or select a different directory. Do not overwrite an existing skill folder. Copying only `SKILL.md` is insufficient because its commands rely on the bundled Python package, presets, and scripts.

If you already have a checkout, Codex also supports discovering a skill through a symbolic link. With the destination absent, link the full checkout instead of cloning again:

```bash
ln -s /absolute/path/to/arxiv-research-radar "$HOME/.agents/skills/arxiv-research-radar"
```

Other hosts that discover `SKILL.md` should use their own documented installation directory and invocation syntax. This repository supplies a portable instruction-and-runtime package; it does not claim verified native integration with every agent platform. If the skill does not appear, follow your host's skill discovery or refresh instructions.

## Say what you research

In a host that supports `$skill-name`, examples include:

> Use $arxiv-research-radar. I study LLM agents, tool use, and agent evaluation. Create a profile for this project and scan the last seven days.

> Use $arxiv-research-radar for exoplanet atmospheres, transmission spectroscopy, and atmospheric retrieval. Store this separately from my AI research collection.

> 用 $arxiv-research-radar，关注分子图学习与性质预测。请按我的方向生成配置，不要沿用数学示例，并告诉我分类和关键词是怎么选的。

> Use $arxiv-research-radar to preview a narrower profile for web and desktop agents. Compare it with my current profile on stored candidates, explain papers added or removed, and leave my active configuration unchanged.

The agent should reuse a profile you already chose. For a new setup it turns your request into arXiv categories, distinct topic IDs, specific phrases, and optional context anchors, then validates the JSON. A vague request may need a short clarification about your actual research questions. The four presets are starting points, not a limit on supported topics; useful coverage still depends on whether the field is represented on arXiv and how well the profile matches its terminology.

User-supplied workspace paths take priority. Without a chosen location, the skill starts with `radar-workspace/profile.json` and `radar-workspace/data` inside the current project. Your research state is kept separate from the installed software folder. Selecting a field does not train a learned preference model.

## Run the bundled tools from any directory

The portable wrapper resolves the package location without requiring `cd` into the installation. This example creates a new AI-agent profile in the current project; it does not fetch papers or start a scheduler:

```bash
radar_skill="$HOME/.agents/skills/arxiv-research-radar"
radar_workspace="$PWD/radar-workspace"
mkdir -p "$radar_workspace"

python3 "$radar_skill/scripts/radar.py" profiles
python3 "$radar_skill/scripts/radar.py" init-profile --preset ai-agents --output "$radar_workspace/profile.json" --name "Agent research" --timezone UTC
python3 "$radar_skill/scripts/radar.py" validate-profile "$radar_workspace/profile.json"
```

`init-profile` refuses to replace an existing output file. Reuse the current profile or choose another output path. Preset names are `math-statistics`, `ai-agents`, `quant-finance`, and `astrophysics`; you can edit the generated JSON or write a [custom profile](configuration.md#a-custom-direction).

With that workspace selected, run a scan and open the local dashboard:

```bash
python3 "$radar_skill/scripts/radar.py" scan --profile "$radar_workspace/profile.json" --data-dir "$radar_workspace/data" --days 7
python3 "$radar_skill/scripts/radar.py" serve --profile "$radar_workspace/profile.json" --data-dir "$radar_workspace/data"
```

The dashboard is at `http://127.0.0.1:8765` while `serve` is running. `--profile` and `--data-dir` belong **after the subcommand**. Pass the same absolute paths for every operation on this collection, even when the agent changes working directories. For a second research area, use another workspace, profile, and data directory.

Relative profile/data paths resolve against the installed skill root, while relative output files resolve against the current working directory. The absolute paths in the examples avoid mixing those locations.

The original `python3 -m radar` commands remain available from a repository checkout. Existing `config/profile.local.json` and environment-variable configuration also remain supported.

## Tune before applying

An agent can export all stored candidate metadata with `export-candidates`, including hidden and unrecommended records, then run `preview-profile` with a proposed profile and an optional baseline. The export excludes personal notes and generated reviews. Preview does not open the research database, call a model or network service, or apply configuration changes. Use absolute paths with the portable wrapper just as for other commands. See [the offline tuning workflow](profile-tuning.md) for a runnable demonstration and a workflow for your own library.

The profile supports required `anchors` and global or topic-local `exclude_keywords`. These are literal phrase rules: an exclusion can fire even when the phrase appears in a negated sentence. Review both additions and removals rather than interpreting a shorter list as better accuracy. The dashboard's **Match details** shows title/abstract matches and why a topic was blocked; unrelated topics with no keyword hits are omitted for readability.

## What is automatic, and what is separate

The runtime performs retrieval, rule-based ranking, duplicate and version tracking, local library storage, and review validation. The host agent can translate your research request into a profile and interpret exported abstracts. Generated reviews must follow [the evidence and version contract](agent-harness.md); they are not full-paper or proof verification.

The dashboard has English and Chinese controls. The current persisted review schema and generated digest still use Chinese `*_zh` fields; changing the research subject or interface language does not change that storage format. An agent can provide a conversational translation separately.

**Installing the skill, choosing a research direction, or starting the dashboard does not enable a daily subscription.** A recurring run needs a separately configured, authorized scheduler with the intended time zone and persistent workspace. The runtime does not send email or chat messages itself. See [scheduling](scheduling.md).

Relevance evaluation remains offline. The bundled synthetic cases test known ranking behavior; use an appropriate independently labeled dataset for your own field before making claims about recommendation accuracy. See [evaluation](evaluation.md).
