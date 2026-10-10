import os
import re
import glob
import logging
from boardrunner.viomapper.codegen.parse import (
    extract_c_code,
    parse_search_replace_blocks,
    ParsingError
)
from boardrunner.viomapper.codegen.patch import (
    apply_search_replace_patches,
    write_patched_file,
    write_model_file,
    PatchError
)
from boardrunner.viomapper.codegen.compile import (
    compile_model,
    format_compilation_error,
    CompilationError
)

log = logging.getLogger(__name__)


def llm_history_next(history_dir: str) -> int:
    """Return the next iteration number for the LLM history directory.

    Scans for existing NNN_prompt.txt files and returns max(N) + 1, or 1 if none exist.
    """
    os.makedirs(history_dir, exist_ok=True)
    existing = glob.glob(os.path.join(history_dir, "*_prompt.txt"))
    if not existing:
        return 1
    nums = []
    for f in existing:
        base = os.path.basename(f)
        prefix = base.split("_prompt.txt")[0]
        if prefix.isdigit():
            nums.append(int(prefix))
    return max(nums) + 1 if nums else 1


_CANONICAL_PATCH_MARKER = "<<<<<<< SEARCH"
# Common ad-hoc patch shapes an LLM might invent on a retry, e.g.
# "### SEARCH" / "### REPLACE" or "SEARCH:" / "REPLACE:" headings.
_ADHOC_PATCH_PATTERN = re.compile(
    r"^\s*(?:#{1,6}\s*)?(SEARCH|REPLACE)\b\s*:?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_FENCED_C_BLOCK_PATTERN = re.compile(r"```[cC]\s*\n.*?```", re.DOTALL)


def _count_c_fences(response_text):
    return len(_FENCED_C_BLOCK_PATTERN.findall(response_text))


def handle_initial_prompt(response_text, output_path, work_dir):
    """Process an initial prompt response: extract C code and write model file.

    Also handles the case where a retry comes back as an incremental
    SEARCH/REPLACE patch instead of a full-file rewrite. If canonical
    ``<<<<<<< SEARCH`` markers are present, the response is applied as a
    patch against ``output_path`` (preserving anything not covered by the
    patch). If the response looks like a patch in some ad-hoc shape
    (multiple partial fenced C blocks with SEARCH / REPLACE headings),
    the write is refused so the previous file is not clobbered.

    Returns:
        Tuple of (success: bool, error_context: str).
    """
    # Case 1: canonical SEARCH/REPLACE patch — delegate to the revised-prompt
    # handler so patches apply against the existing file on disk.
    if _CANONICAL_PATCH_MARKER in response_text:
        log.info(
            "Initial-prompt response contains SEARCH/REPLACE markers; "
            "applying as a patch to %s instead of overwriting.",
            output_path,
        )
        return handle_revised_prompt(response_text, [output_path], work_dir)

    # Case 2: ad-hoc patch shape (headings like "### SEARCH" / "### REPLACE",
    # or multiple partial C fences). Reject rather than concatenate — that
    # was the failure mode that produced orphan switch blocks glued to a
    # duplicated file body.
    fence_count = _count_c_fences(response_text)
    adhoc_hits = {m.group(1).upper() for m in _ADHOC_PATCH_PATTERN.finditer(response_text)}
    looks_like_adhoc_patch = (
        {"SEARCH", "REPLACE"}.issubset(adhoc_hits) or fence_count > 1
    )
    if looks_like_adhoc_patch:
        log.error(
            "Initial-prompt response looks like a patch (%d C fences, "
            "ad-hoc markers=%s) but not in canonical SEARCH/REPLACE "
            "format. Refusing to overwrite %s.",
            fence_count, sorted(adhoc_hits), output_path,
        )
        error_context = (
            "Your response looks like an incremental patch but is not in "
            "the expected format for an initial prompt.\n"
            "Either send the COMPLETE C device model in a single fenced "
            "```c ... ``` code block, or use the canonical SEARCH/REPLACE "
            "format:\n"
            "// FILE: %s\n"
            "<<<<<<< SEARCH\n"
            "[exact old code]\n"
            "=======\n"
            "[new code]\n"
            ">>>>>>> REPLACE\n"
            "Do not use ``` \\`\\`\\`c ``` blocks with `### SEARCH` / "
            "`### REPLACE` headings — the framework will not interpret them."
            % os.path.basename(output_path)
        )
        return False, error_context

    # Case 3: normal full-file rewrite.
    try:
        c_code = extract_c_code(response_text)
    except ParsingError as e:
        log.error("Failed to extract C code from LLM response: %s", str(e))
        error_context = (
            "Failed to extract C code from the response. "
            "The response did not contain a properly fenced ```c code block.\n"
            "Please provide the complete C device model in a single fenced "
            "```c ... ``` code block."
        )
        return False, error_context

    write_model_file(output_path, c_code)
    log.info("Model written to %s", output_path)
    return True, ""


def handle_revised_prompt(response_text, output_paths, work_dir):
    """Process a revised prompt response: parse and apply SEARCH/REPLACE patches.

    Returns:
        Tuple of (success: bool, error_context: str).
    """
    try:
        patches = parse_search_replace_blocks(response_text)
    except ParsingError as e:
        log.error("Failed to parse SEARCH/REPLACE blocks: %s", str(e))
        error_context = (
            "Failed to parse SEARCH/REPLACE blocks from the response.\n"
            "Error: %s\n"
            "Please provide corrections using the exact SEARCH/REPLACE format:\n"
            "// FILE: <filename>\n"
            "<<<<<<< SEARCH\n"
            "[exact old code]\n"
            "=======\n"
            "[new code]\n"
            ">>>>>>> REPLACE" % str(e)
        )
        return False, error_context

    from collections import defaultdict
    patches_by_path = defaultdict(list)

    for patch in patches:
        if patch.target_file:
            matched = None
            for p in output_paths:
                if os.path.basename(p) == patch.target_file:
                    matched = p
                    break
            if matched:
                patches_by_path[matched].append(patch)
            else:
                log.warning("Target file %s not found in output arguments (-o). Defaulting to %s", patch.target_file, output_paths[0])
                patches_by_path[output_paths[0]].append(patch)
        else:
            patches_by_path[output_paths[0]].append(patch)

    # First pass: try to apply all patches in-memory to ensure atomic success
    patched_files = {}
    for path, file_patches in patches_by_path.items():
        try:
            patched_content = apply_search_replace_patches(path, file_patches)
            patched_files[path] = patched_content
        except PatchError as e:
            log.error("Patch application failed: %s", str(e))
            # Read the current file content to include in error context
            current_content = ""
            try:
                with open(path, "r", encoding="utf-8") as f:
                    current_content = f.read()
            except OSError:
                pass

            error_context = (
                "Patch application failed.\n"
                "Error: %s\n\n"
                "The SEARCH text in block #%d was not found in the file: %s.\n"
                "This usually means the SEARCH text does not exactly match the "
                "current file content (check whitespace, indentation, and exact characters).\n\n"
                "Current file content (first 5000 chars):\n%s"
                % (str(e), e.block_index, os.path.basename(path), current_content[:5000])
            )
            return False, error_context

    # Second pass: commit all patches to disk (atomic write)
    for path, patched_content in patched_files.items():
        write_patched_file(path, patched_content)
        log.info("Patches applied and saved to %s", path)

    return True, ""


def handle_compilation(sdk_dir):
    """Run model compilation and return result.

    Returns:
        Tuple of (success: bool, error_context: str, is_setup_error: bool).
    """
    try:
        success, build_output = compile_model(sdk_dir)
    except CompilationError as e:
        log.error("Compilation setup failed: %s", str(e))
        return False, str(e), True

    if not success:
        error_context = format_compilation_error(build_output)
        log.error("Model compilation failed. See error details above.")
        return False, error_context, False

    log.info("Model compiled successfully.")
    return True, "", False
