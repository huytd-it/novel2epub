$results = Get-Content "D:\Projects\novel2epub\.understand-anything\tmp\ua-file-extract-results-24.json" -Raw | ConvertFrom-Json

$nodes = @()
$edges = @()

$summaries = @{
    ".opencode/skills/openspec-sync-specs/SKILL.md" = @{
        summary = "Skill definition for openspec-sync-specs: syncs delta specs from a change to main specs without archiving."
        tags = @("skill","opencode","openspec")
        complexity = "simple"
    }
    ".specify/extensions/.registry" = @{
        summary = "Specify extension registry listing installed extensions with registered commands and manifest hash."
        tags = @("config","registry","speckit")
        complexity = "simple"
    }
    ".specify/extensions/agent-context/commands/speckit.agent-context.update.md" = @{
        summary = "Command doc for updating the coding agent context file with managed SPECKIT block."
        tags = @("speckit","agent-context","command")
        complexity = "simple"
    }
    ".specify/extensions/agent-context/scripts/bash/update-agent-context.sh" = @{
        summary = "Bash script that refreshes the managed Spec Kit section in coding agent context files."
        tags = @("speckit","agent-context","bash","script")
        complexity = "moderate"
    }
    ".specify/extensions/agent-context/scripts/powershell/update-agent-context.ps1" = @{
        summary = "PowerShell script mirroring update-agent-context.sh for Windows."
        tags = @("speckit","agent-context","powershell","script")
        complexity = "moderate"
    }
    ".specify/memory/constitution.md" = @{
        summary = "novel2epub project constitution v1.0.0 defining five core principles."
        tags = @("constitution","governance","project")
        complexity = "moderate"
    }
    ".specify/workflows/speckit/workflow.yml" = @{
        summary = "Spec Kit workflow definition YAML for the speckit workflow."
        tags = @("speckit","workflow","config")
        complexity = "simple"
    }
    ".specify/workflows/workflow-registry.json" = @{
        summary = "Workflow registry JSON mapping workflow names to their definition file paths."
        tags = @("speckit","workflow","config")
        complexity = "simple"
    }
    ".understand-anything/.understandignore" = @{
        summary = "Gitignore-style patterns for files/directories to exclude from codebase analysis."
        tags = @("config","ignore","understand-anything")
        complexity = "simple"
    }
    ".understand-anything/config.json" = @{
        summary = "understand-anything configuration specifying output language setting."
        tags = @("config","understand-anything")
        complexity = "simple"
    }
    "app/__init__.py" = @{
        summary = "Package init for the novel2epub FastAPI Web UI module."
        tags = @("web-ui","fastapi","package-init")
        complexity = "simple"
    }
    "app/static/style.css" = @{
        summary = "Static CSS stylesheet for the novel2epub Web UI."
        tags = @("css","web-ui","styling")
        complexity = "simple"
    }
    "configs/novel.yaml" = @{
        summary = "Full YAML configuration for a novel project: metadata, crawl, translation, and output."
        tags = @("config","yaml","novel","crawl","translate","output")
        complexity = "moderate"
    }
    "novel2epub/presets/__init__.py" = @{
        summary = "Preset loader module for CLI translator configuration with available() and load()."
        tags = @("presets","config","loader","python")
        complexity = "simple"
    }
    "novel2epub/presets/go.py" = @{
        summary = "OpenCode Go translation preset: command, model, Vietnamese translation prompts."
        tags = @("presets","opencode","go","translation","vietnamese")
        complexity = "simple"
    }
    "openspec/changes/ai-source-preset-builder/specs/firecrawl-removal/spec.md" = @{
        summary = "Delta spec for removing Firecrawl engine support."
        tags = @("openspec","spec","firecrawl","removal","engine")
        complexity = "moderate"
    }
    "openspec/changes/ai-source-preset-builder/specs/preset-builder/spec.md" = @{
        summary = "Delta spec for AI-powered source preset builder."
        tags = @("openspec","spec","preset-builder","ai","source")
        complexity = "moderate"
    }
    "openspec/changes/archive/2026-06-22-add-paginated-chapter-support/specs/chapter-pagination/spec.md" = @{
        summary = "Archived delta spec for multi-page chapter pagination support."
        tags = @("openspec","spec","chapter-pagination","archive")
        complexity = "moderate"
    }
    "openspec/changes/improve-sources-ui/specs/sources-ui/spec.md" = @{
        summary = "Delta spec for improving the Web UI source presets management page."
        tags = @("openspec","spec","sources-ui","web-ui","ux")
        complexity = "moderate"
    }
    "openspec/specs/chapter-pagination/spec.md" = @{
        summary = "Main specification for chapter pagination support."
        tags = @("openspec","spec","chapter-pagination")
        complexity = "moderate"
    }
    "specs/001-refactor-toc/checklists/requirements.md" = @{
        summary = "Specification quality checklist for refactor-toc feature."
        tags = @("specs","checklist","refactor-toc")
        complexity = "simple"
    }
    "specs/001-refactor-toc/contracts/cli.md" = @{
        summary = "CLI contract for refactored TOC: fetch, translate, list, crawl, translate chapters."
        tags = @("specs","contract","cli","refactor-toc")
        complexity = "moderate"
    }
    "specs/001-refactor-toc/contracts/web-ui.md" = @{
        summary = "Web UI contract for refactored TOC: ebook overview, fetch TOC, chapter list, bulk actions."
        tags = @("specs","contract","web-ui","refactor-toc")
        complexity = "moderate"
    }
    "specs/002-opencode-go-preset/checklists/requirements.md" = @{
        summary = "Specification quality checklist for OpenCode Go Translation & AI Preset."
        tags = @("specs","checklist","opencode","go","preset")
        complexity = "simple"
    }
    "specs/002-opencode-go-preset/contracts/cli.md" = @{
        summary = "CLI config contract for OpenCode Go preset: schema, resolution rules, examples, errors."
        tags = @("specs","contract","cli","opencode","go","preset")
        complexity = "moderate"
    }
}

$sectionDesc = @{
    # agent-context
    "Update Coding Agent Context" = "Top-level heading describing behavior and execution of agent context updates."
    "Behavior" = "Describes expected behavior when updating the agent context."
    "Execution" = "Execution details for agent context update command."
    # constitution
    "novel2epub Constitution" = "Top-level constitution heading for the project."
    "Core Principles" = "Five core principles governing all features."
    "I. Source Metadata Completeness" = "Every feature must preserve complete source-level metadata for EPUB building."
    "II. Translation Fidelity and Glossary Discipline" = "CN-to-VI translation must follow traditional edit rules with Sino-Vietnamese naming."
    "III. Idempotent Crawl/Translate/Build Pipeline" = "Crawler, translator, EPUB builder must be resumable and idempotent across CLI/Web UI."
    "IV. Chapter-Level User Control" = "Users can inspect/act on chapters independently with ordering, filtering, range selection."
    "V. Independently Testable Delivery" = "Every user-facing story independently testable through CLI, Web UI, or service tests."
    "Product Constraints" = "Python 3.10+, disk storage under data/<slug>/, CLI-Web UI compatibility, engine-selectable crawling."
    "Development Workflow" = "Plans must pass Constitution Check; specs define independently deliverable stories."
    "Governance" = "Constitution amendment rules, semver versioning, review requirements."
    # workflow.yml
    "schema_version" = "Workflow schema version declaration."
    "workflow" = "Workflow metadata: name, description, and version."
    "requires" = "Declares required inputs and their metadata."
    "inputs" = "Workflow input parameter definitions."
    "steps" = "Ordered workflow steps to execute."
    # workflow-registry.json
    "workflows" = "Registered workflows map with definition paths."
    # understand-anything config
    "outputLanguage" = "Output language setting for analysis output."
    # configs/novel.yaml
    "novel" = "Novel metadata: title, author, language, slug."
    "crawl" = "Crawl config: engine, TOC URL, selectors, pagination, encoding."
    "translate" = "Translation config: backend type, style, glossary, CLI command/model/prompts."
    "output" = "Output config: data directory and EPUB file path."
}

# Default section description generator
function Get-SectionSummary($heading) {
    if ($sectionDesc.ContainsKey($heading)) { return $sectionDesc[$heading] }
    if ($heading -match "^Scenario:") { return "Scenario: $($heading.Substring(9).Trim())" }
    if ($heading -match "^Requirement:") { return "Requirement: $($heading.Substring(12).Trim())" }
    $short = if ($heading.Length -gt 80) { $heading.Substring(0,80) + "..." } else { $heading }
    return $short
}

foreach ($r in $results.results) {
    $path = $r.path
    $lang = $r.language
    $cat = $r.fileCategory
    $lines = $r.totalLines
    $name = Split-Path $path -Leaf

    $info = $summaries[$path]
    if (-not $info) {
        $info = @{ summary = $name; tags = @(); complexity = "simple" }
    }

    # File node
    $fileNode = @{
        id = "file:$path"
        type = "file"
        name = $name
        filePath = $path
        summary = $info.summary
        tags = $info.tags
        complexity = $info.complexity
    }
    $nodes += $fileNode
    $fileId = $fileNode.id

    # Sections
    if ($r.sections) {
        foreach ($s in $r.sections) {
            $snode = @{
                id = "section:$($path):$($s.heading)"
                type = "section"
                name = $s.heading
                filePath = $path
                lineRange = @($s.line, $s.line)
                summary = Get-SectionSummary $s.heading
                tags = if ($s.heading -match "Scenario:") { @("scenario") } elseif ($s.heading -match "Requirement:") { @("requirement") } else { @("section") }
                complexity = "simple"
            }
            $nodes += $snode
            $edges += @{source=$fileId; target=$snode.id; type="contains"; direction="forward"; weight=1.0}
        }
    }

    # Functions
    if ($r.functions) {
        foreach ($f in $r.functions) {
            $fnode = @{
                id = "function:$($path):$($f.name)"
                type = "function"
                name = $f.name
                filePath = $path
                lineRange = @($f.startLine, $f.endLine)
                summary = if ($f.name -eq "available") { "Returns sorted list of available preset names." }
                          elseif ($f.name -eq "load") { "Loads a preset by name via dynamic import, calls mod.load_preset()." }
                          elseif ($f.name -eq "load_preset") { "Returns dict of CliTranslatorConfig overrides for OpenCode Go." }
                          else { "Function $($f.name)" }
                tags = if ($path -match "presets") { @("presets","config") } else { @() }
                complexity = "simple"
            }
            $nodes += $fnode
            $edges += @{source=$fileId; target=$fnode.id; type="contains"; direction="forward"; weight=1.0}
        }
    }

    # Call graph edges
    if ($r.callGraph) {
        foreach ($cg in $r.callGraph) {
            $callerId = "function:$($path):$($cg.caller)"
            $calleeId = if ($cg.callee -match "\." -or $cg.callee -match "^[_A-Z]") {
                # External or stdlib call - reference as external
                "function:$($path):$($cg.caller)"
            } else {
                "function:$($path):$($cg.callee)"
            }
            # Only add edges between functions that are in our nodes
            # For internal calls
            $targetFunc = $r.functions | Where-Object { $_.name -eq $cg.callee }
            if ($targetFunc) {
                $edges += @{
                    source = $callerId
                    target = "function:$($path):$($cg.callee)"
                    type = "calls"
                    direction = "forward"
                    weight = 0.5
                }
            }
        }
    }
}

# Cross-file relationships
# presets/__init__.py -> presets/go.py (imports via importlib)
$edges += @{
    source = "file:novel2epub/presets/__init__.py"
    target = "file:novel2epub/presets/go.py"
    type = "imports"
    direction = "forward"
    weight = 0.7
}

# configs/novel.yaml references the go preset implicitly
$edges += @{
    source = "file:configs/novel.yaml"
    target = "file:novel2epub/presets/go.py"
    type = "references"
    direction = "forward"
    weight = 0.4
}

# specs/002-opencode-go-preset folder cross-refs
$edges += @{
    source = "file:specs/002-opencode-go-preset/checklists/requirements.md"
    target = "file:specs/002-opencode-go-preset/contracts/cli.md"
    type = "references"
    direction = "forward"
    weight = 0.4
}

# specs/001-refactor-toc folder cross-refs
$edges += @{
    source = "file:specs/001-refactor-toc/checklists/requirements.md"
    target = "file:specs/001-refactor-toc/contracts/cli.md"
    type = "references"
    direction = "forward"
    weight = 0.4
}
$edges += @{
    source = "file:specs/001-refactor-toc/checklists/requirements.md"
    target = "file:specs/001-refactor-toc/contracts/web-ui.md"
    type = "references"
    direction = "forward"
    weight = 0.4
}

# chapter-pagination spec pairs (archived change -> main spec)
$edges += @{
    source = "file:openspec/changes/archive/2026-06-22-add-paginated-chapter-support/specs/chapter-pagination/spec.md"
    target = "file:openspec/specs/chapter-pagination/spec.md"
    type = "references"
    direction = "forward"
    weight = 0.6
}

# .specify/extension scripts reference the command doc
$edges += @{
    source = "file:.specify/extensions/agent-context/scripts/bash/update-agent-context.sh"
    target = "file:.specify/extensions/agent-context/commands/speckit.agent-context.update.md"
    type = "references"
    direction = "forward"
    weight = 0.4
}
$edges += @{
    source = "file:.specify/extensions/agent-context/scripts/powershell/update-agent-context.ps1"
    target = "file:.specify/extensions/agent-context/commands/speckit.agent-context.update.md"
    type = "references"
    direction = "forward"
    weight = 0.4
}

$output = @{
    nodes = $nodes
    edges = $edges
}

$output | ConvertTo-Json -Depth 4 | Out-File "D:\Projects\novel2epub\.understand-anything\intermediate\batch-24.json" -Encoding UTF8

Write-Host "Nodes: $($nodes.Count)"
Write-Host "Edges: $($edges.Count)"
Write-Host "Written to batch-24.json"
