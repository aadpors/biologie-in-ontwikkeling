import json  # Generate a static, inspectable inventory of MCQ cards.
import re
from pathlib import Path
import fitz
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "exam-snippets"
OUT.mkdir(exist_ok=True)

def discover_exams():
    """Discover every available Havo/Vwo exam PDF and its matching marking scheme.

    Accept both ordinary opgaven PDFs (*-o.pdf) and supplement-named
    opgaven PDFs (*-o-spr.pdf). New exam years/periods are included
    automatically; an unmatched exam or marking scheme is a hard error.
    """
    exam_dir = ROOT / "examens"
    pattern = re.compile(r"^(ha|vw)-1018-a-(\d{2})-(\d)-o(?:-[a-z0-9]+)?\.pdf$", re.I)
    discovered = []
    for source in sorted(exam_dir.glob("*.pdf")):
        match = pattern.match(source.name)
        if not match:
            continue
        level_code, short_year, period = match.groups()
        # The practice bank covers the complete 2024–2026 exam set. Older
        # archived source PDFs without a paired correction scheme are not part
        # of this bank and must not block reprocessing of the supported years.
        if int(short_year) < 24 or int(short_year) > 26:
            continue
        cv = exam_dir / f"{level_code}-1018-a-{short_year}-{period}-c.pdf"
        if not cv.is_file():
            raise FileNotFoundError(
                f"Exam {source.name} has no matching correction scheme: {cv.name}"
            )
        year = f"20{short_year}"
        level = "Havo" if level_code.lower() == "ha" else "Vwo"
        exam_id = f"{level_code.lower()}{short_year}t{period}"
        discovered.append((exam_id, level, year, period,
                           str(source.relative_to(ROOT)), str(cv.relative_to(ROOT))))
    if not discovered:
        raise RuntimeError(f"No Havo/Vwo exam PDFs found in {exam_dir}")
    keys = [(item[0], item[1], item[2], item[3]) for item in discovered]
    if len(keys) != len(set(keys)):
        raise RuntimeError(f"Multiple opgaven PDFs found for the same exam: {keys}")
    return discovered


EXAMS = discover_exams()

def appendix_pdfs_for_exam(exam_pdf):
    """Find separately published printable answer/work appendices for an exam."""
    source = Path(exam_pdf)
    stem = source.stem
    # The exam identifier is stable across opgaven, correction and appendix files.
    base = re.sub(r"-o(?:-[a-z0-9]+)?$", "", stem, flags=re.I)
    appendix_suffix = re.compile(
        r"^(?:-u|-ub|-b|-bijlage|-bijlagen|-uitwerkbijlage|-uitwerkblad"
        r"|-antwoordblad|-werkblad|-tekenblad|-bijl"
        r"|-o-(?:bijlage|bijlagen|uitwerkbijlage|uitwerkblad|antwoordblad|werkblad))"
        r"(?:[-_][a-z0-9]+)?$",
        re.I,
    )
    found = []
    for candidate in sorted((ROOT / "examens").glob("*.pdf")):
        candidate_stem = candidate.stem
        candidate_lower = candidate_stem.lower()
        base_lower = base.lower()
        if base_lower not in candidate_lower:
            continue
        suffix = candidate_stem[candidate_lower.index(base_lower) + len(base):]
        named_as_appendix = re.search(
            r"uitwerk|bijlage|antwoordblad|werkblad|tekenblad",
            candidate_stem,
            re.I,
        )
        if appendix_suffix.fullmatch(suffix) or named_as_appendix:
            found.append(candidate.relative_to(ROOT).as_posix())
    return found


def attach_appendix_links(records):
    # Only expose the appendix on cards whose own prompt/context refers to it.
    # This avoids showing an unrelated worksheet on every question in an exam.
    appendix_reference = re.compile(
        r"uitwerkbijlage|uitwerkblad|antwoordblad|tekenblad|werkblad|"
        r"bijlage(?:\s+(?:invullen|gebruiken|raadplegen))?",
        re.I,
    )
    for record in records:
        attachments = appendix_pdfs_for_exam(record["pdf"])
        question_text = " ".join(
            str(record.get(field, "")) for field in ("q", "source")
        )
        if attachments and appendix_reference.search(question_text):
            record["attachmentPdfs"] = attachments

SELECTED_CONTEXTS = {
    ("ha24t1", 1), ("ha24t1", 8),
    ("ha24t1", 10), ("ha24t2", 3), ("ha24t2", 6), ("ha24t2", 7), ("vw24t1", 1), ("vw24t2", 1), ("vw24t2", 2),
    ("vw25t1", 14), ("vw25t1", 15), ("vw25t1", 16), ("vw25t1", 17), ("vw25t1", 18),
    ("ha25t1", 1), ("ha25t1", 3), ("ha25t1", 5),
    ("ha26t1", 4), ("ha26t1", 5), ("ha26t1", 7), ("ha26t1", 8), ("ha26t1", 15), ("ha26t1", 16),
    ("vw26t1", 1), ("vw26t1", 2), ("vw26t1", 12), ("vw26t1", 14), ("vw26t1", 16), ("vw26t1", 20),
    ("ha25t2", 3), ("ha25t2", 9),
    ("vw25t2", 6), ("vw25t2", 8),
    ("ha26t2", 3), ("ha26t2", 9),
    ("vw26t2", 14), ("vw26t2", 24),
}
# Question-number false positives elsewhere in Havo 2024-I must never
# overwrite the correctly anchored page-2/page-5 image files.
SELECTED_CONTEXT_PAGES = {("ha24t1", 1): 2, ("ha24t1", 8): 5}

HEADER_RE = re.compile(r"^(?:[HV][AW]-1018-a-\d{2}-\d-o|\d+\s*/\s*\d+|lees verder|einde|vraag\s+antwoord\s+scores|vraag|antwoord|scores)\b", re.I)
MARKER_RE = re.compile(r"^\s*(\d+)\s*p\s+(\d{1,2})(?:\s+|$)", re.I)
NUMBER_FIRST_MARKER_RE = re.compile(r"^\s*(\d{1,2})\s+(\d+)\s*p(?:\s+|$)", re.I)
NUMBER_RE = re.compile(r"^\s*(\d{1,2})\s*$")
OPTION_RE = re.compile(r"^\s*([A-F])(?:\s+(.+))?\s*$")

# Extra room below every text-based crop so glyph descenders (g, j, p, q, y)
# are never clipped by a tight PDF text bounding box.
BOTTOM_TEXT_PADDING = 0

def save_page_crop(page, rect, output, lines, excluded_ranges=(), scale=1.8):
    """Render a full-width crop and remove earlier question blocks without leaving blank bands."""
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=rect, alpha=False)
    source = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    exclusions = []
    for start, end in excluded_ranges:
        if start >= len(lines) or end <= start:
            continue
        top = max(rect.y0, lines[start]["bbox"][1] - 2)
        bottom = min(rect.y1, lines[min(end - 1, len(lines) - 1)]["bbox"][3] + 2)
        if bottom > top:
            exclusions.append((top, bottom))
    exclusions.sort()
    merged = []
    for top, bottom in exclusions:
        if merged and top <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], bottom))
        else:
            merged.append((top, bottom))
    segments = []
    cursor_y = rect.y0
    for top, bottom in merged:
        if top > cursor_y:
            segments.append(source.crop((
                0,
                max(0, int((cursor_y - rect.y0) * scale)),
                source.width,
                min(source.height, int((top - rect.y0) * scale)),
            )))
        cursor_y = max(cursor_y, bottom)
    if cursor_y < rect.y1:
        segments.append(source.crop((
            0,
            max(0, int((cursor_y - rect.y0) * scale)),
            source.width,
            source.height,
        )))
    segments = [segment for segment in segments if segment.height > 1]
    if not segments:
        raise RuntimeError(f"Question crop became empty after excluding prior questions: {output}")
    result = Image.new("RGB", (source.width, sum(segment.height for segment in segments)), "white")
    y = 0
    for segment in segments:
        result.paste(segment, (0, y))
        y += segment.height
    result.save(output, quality=94)


def footer_boundary(page, lines):
    """Find the end of exam content before the printed footer."""
    footer_re = re.compile(
        r"(?:[HV][AW]-1018-a-|\b\d{1,2}\s*/\s*\d{1,2}\b|"
        r"centraal examen|ministerie van onderwijs|biologie\s*[-|])", re.I
    )
    hits = [line["bbox"][1] for line in lines
            if line["bbox"][1] >= page.rect.height * 0.88 and footer_re.search(line["text"])]
    return max(1, min(hits, default=page.rect.height - 18) - 3)


def context_image_fragments(page, lines, indices, prefix, number, question_top, bottom_limit, previous_ranges=(), scale=1.8, end_anchor=None, start_anchor=None):
    """Render one complete, full-width context crop, preserving figures and tables."""
    # Havo 2024-I questions 1–9 share the heart-valve introduction printed
    # before question 1 on the preceding page. Question 3 starts on page 3,
    # where the page-local detector cannot see that introduction. Reuse the
    # already rendered original context image instead of manufacturing an
    # almost-empty fallback crop from page 3.
    if prefix == "ha24t1" and number == 3:
        shared = OUT / "context-ha24t1-q1-complete.jpg"
        if not shared.is_file():
            raise RuntimeError("Shared Havo 2024-I heart-valve context for question 3 was not rendered")
        return ["exam-snippets/context-ha24t1-q1-complete.jpg"]

    # Havo 2025-I question 26: the three numbered statements belong to
    # the question itself, not to the shared Bajau context. End the context
    # crop before that heading so the statements are shown exactly once.
    if prefix == "ha25t1" and number == 26:
        start_anchor = "De Bajau"
        end_anchor = "Hieronder staan drie uitspraken."
    if start_anchor and end_anchor:
        start_hits = page.search_for(start_anchor)
        end_hits = page.search_for(end_anchor)
        if not start_hits or not end_hits:
            raise RuntimeError(
                f"Could not locate anchored context for {prefix} question {number}: "
                f"start={start_anchor!r}, end={end_anchor!r}"
            )
        top = max(0, min(rect.y0 for rect in start_hits) - 5)
        if prefix == "ha25t1" and number == 26:
            # The heading introduces the statements and belongs with the
            # question, so the shared context must stop before the heading.
            bottom = min(bottom_limit, min(rect.y0 for rect in end_hits) - 2)
        else:
            bottom = min(bottom_limit, max(rect.y1 for rect in end_hits) + 1)
        if bottom <= top:
            raise RuntimeError(f"Invalid anchored context bounds for {prefix} question {number}")
        pix = page.get_pixmap(
            matrix=fitz.Matrix(scale, scale),
            clip=fitz.Rect(0, top, page.rect.width, bottom),
            alpha=False,
        )
        crop = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        padded = Image.new("RGB", (crop.width, crop.height + 14), "white")
        padded.paste(crop, (0, 0))
        name = f"context-{prefix}-q{number}-complete.jpg"
        padded.save(OUT / name, quality=94)
        return [f"exam-snippets/{name}"]

    ordered = sorted({i for i in indices if 0 <= i < len(lines) and lines[i]["bbox"][1] < question_top},
                     key=lambda i: (round(lines[i]["bbox"][1], 1), lines[i]["bbox"][0]))
    if not ordered:
        return []

    # Start at the first line belonging to this question's context. Include
    # figures/drawings that overlap that context, but do not pull in artwork
    # from earlier question blocks on the same page.
    context_top = min(lines[i]["bbox"][1] for i in ordered)
    visual_rects = [
        rect for info in page.get_images(full=True)
        for rect in page.get_image_rects(info[0])
        if rect.y0 < question_top and rect.y1 > context_top
    ]
    visual_rects.extend(
        drawing["rect"] for drawing in page.get_drawings()
        if drawing["rect"].width > 8 and drawing["rect"].height > 8
        and drawing["rect"].y0 < question_top and drawing["rect"].y1 > context_top
    )
    if visual_rects:
        context_top = min(context_top, min(rect.y0 for rect in visual_rects))

    context_top = max(0, context_top - 10)
    # End below the complete final context text line, not merely a fixed
    # distance above the next question marker. The latter clipped descenders
    # and the lower edge of the final line on tightly spaced exam pages.
    final_context_text_bottom = max(lines[i]["bbox"][3] for i in ordered)
    # question_top is already inset from the printed question marker. Keep
    # the final context line intact and leave a small white lower margin.
    question_boundary = min(bottom_limit, question_top - 2)
    # On two-column pages, text from the neighbouring column can share the
    # same vertical band as the question marker. Preserve the complete context
    # line rather than cutting it at the marker's y-coordinate; the question
    # crop itself remains a separate image.
    # Keep at least a small gap before the question marker. If the context
    # line ends earlier, retain six points of breathing room; never extend the
    # context crop into the question merely to satisfy that padding.
    context_bottom = min(
        bottom_limit,
        question_top - 1,
        final_context_text_bottom + 18,
    )
    if prefix == "ha24t1" and number == 1:
        # The heart-valve diagram is placed below the "afbeelding 1" label.
        # Include the complete figure up to (but not into) question 1.
        context_bottom = min(bottom_limit, question_top - 2)
    if end_anchor:
        end_hits = page.search_for(end_anchor)
        if not end_hits:
            raise RuntimeError(
                f"Could not find the end of the context for {prefix} question {number}: {end_anchor!r}"
            )
        # Exact final phrase is more reliable than inferred line ordering for
        # the multi-question hippopotamus passage.
        context_bottom = min(
            bottom_limit,
            max(rect.y1 for rect in end_hits) + 1,
        )
    # If a diagram/photo begins in the context and extends below the printed
    # question marker, retain the complete visual. Several exam figures cross
    # that boundary (e.g. Havo 2024-I q27 and Vwo 2025-I q11); stopping at the
    # marker silently removed the lower half of the figure.
    if visual_rects:
        context_bottom = min(
            bottom_limit,
            max(context_bottom, max(rect.y1 for rect in visual_rects) + 10),
        )
    # A very shallow fragment is not a usable context card. Let the
    # bounded page-local fallback preserve the preceding context instead.
    if context_bottom <= context_top + 35:
        return []

    name = f"context-{prefix}-q{number}-complete.jpg"
    output_path = OUT / name
    save_page_crop(
        page,
        fitz.Rect(0, context_top, page.rect.width, context_bottom),
        output_path,
        lines,
        previous_ranges,
        scale=scale,
    )
    if end_anchor:
        # Keep a clean lower margin without pulling the next paragraph into
        # the crop. The glyphs are already fully rendered above this padding.
        with Image.open(output_path) as crop:
            padded = Image.new("RGB", (crop.width, crop.height + 14), "white")
            padded.paste(crop, (0, 0))
            padded.save(output_path, quality=94)
    return [f"exam-snippets/{name}"]

def fallback_context_fragment(page, lines, prefix, number, question_top, previous_ranges=(), scale=1.8):
    """Keep preceding shared text/figures when semantic context-line detection finds no text."""
    top = 12
    bottom = min(question_top - 2, page.rect.height - 20)
    if bottom <= top + 2:
        return []
    name = f"context-{prefix}-q{number}-fallback.jpg"
    save_page_crop(
        page,
        fitz.Rect(0, top, page.rect.width, bottom),
        OUT / name,
        lines,
        previous_ranges,
        scale=scale,
    )
    return [f"exam-snippets/{name}"]


def trim_question_bottom_rule(path):
    """Remove a full-width page separator accidentally captured below a prompt."""
    with Image.open(path) as source:
        image = source.convert("RGB")
    gray = image.convert("L")
    width, height = gray.size
    pixels = gray.load()
    first_rule = None
    start = max(0, height - 16)
    for y in range(start, height - 1):
        dark = sum(1 for x in range(width) if pixels[x, y] < 235)
        if dark >= width * 0.70:
            # A true separator is a long, thin line with clear whitespace above
            # it. Do not trim the lower edge of a diagram/table whose content
            # reaches the same boundary.
            previous = []
            for py in range(max(0, y - 3), y):
                previous.append(sum(1 for x in range(width) if pixels[x, py] < 235) / width)
            if previous and max(previous) < 0.15:
                first_rule = y
                break
    if first_rule is not None:
        crop_bottom = max(1, first_rule - 1)
        trimmed = image.crop((0, 0, width, crop_bottom))
        result = Image.new("RGB", (width, crop_bottom + 4), "white")
        result.paste(trimmed, (0, 0))
        result.save(path, quality=94)
        trimmed.close()
        result.close()
    gray.close()
    image.close()


def line_records(page):
    records = []
    data = page.get_text("dict")
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            txt = "".join(s.get("text", "") for s in spans).strip()
            if not txt:
                continue
            size = max((s.get("size", 0) for s in spans), default=0)
            bold = any("bold" in s.get("font", "").lower() for s in spans)
            records.append({
                "text": re.sub(r"\s+", " ", txt),
                "bbox": line.get("bbox", [0, 0, 0, 0]),
                "size": size,
                "bold": bold,
            })
    # Detect a genuine two-column page before sorting. A simple top-to-bottom
    # sort interleaves the columns, which can attach an unrelated context or even
    # another question's answer options to the current question.
    if len(records) >= 8:
        xs = sorted(r["bbox"][0] for r in records)
        gaps = [(xs[i + 1] - xs[i], i) for i in range(len(xs) - 1)]
        gap, split = max(gaps, default=(0, 0))
        left_count, right_count = split + 1, len(xs) - split - 1
        if gap >= page.rect.width * 0.12 and left_count >= 4 and right_count >= 4:
            split_x = (xs[split] + xs[split + 1]) / 2
            for record in records:
                record["column"] = 0 if record["bbox"][0] < split_x else 1
            records.sort(key=lambda x: (x["column"], round(x["bbox"][1], 1), x["bbox"][0]))
        else:
            records.sort(key=lambda x: (round(x["bbox"][1], 1), x["bbox"][0]))
    else:
        records.sort(key=lambda x: (round(x["bbox"][1], 1), x["bbox"][0]))
    return records

def find_markers(lines, allow_multiline_number_first=False):
    markers = []
    prompt_starts = re.compile(
        r"^(hieronder|wat|wie|welk|welke|waar|wanneer|waarom|hoe|door|wordt|zal|stroomt|vindt|behoort|bij|kruis|vul|teken|neem|gedurende|draagt|uit|via|maak|leg|verklaar|beargumenteer|beschrijf|noteer|geef|noem|is|zijn|neemt|beoordeel|schrijf|bereken|licht|beredeneer|laat|de vorming|tot welke|in welk|op welk|op welke|hoeveel|waardoor)",
        re.I,
    )
    point_re = re.compile(r"^\s*(\d+)\s*p\s*$", re.I)

    def prompt_start_before(index):
        for j in range(index - 1, max(index - 16, -1), -1):
            if prompt_starts.match(lines[j]["text"]):
                return j
            if (
                (lines[j]["size"] >= 13 or (lines[j]["bold"] and lines[j]["size"] >= 12.5))
                and len(lines[j]["text"]) < 90
                and not re.match(r"^(afbeelding|tabel|grafiek|legenda)(?:\s+\d+)?$", lines[j]["text"], re.I)
            ):
                break
        return index

    for i, record in enumerate(lines):
        number_first = NUMBER_FIRST_MARKER_RE.match(record["text"])
        if number_first:
            inline_prompt = record["text"][number_first.end():].strip()
            start = i if inline_prompt else prompt_start_before(i)
            markers.append({
                "line": start, "number_line": i, "points_line": i,
                "number": int(number_first.group(1)), "points": int(number_first.group(2)),
                "inline_prompt": inline_prompt
            })
            continue

        inline = MARKER_RE.match(record["text"])
        if inline:
            inline_prompt = record["text"][inline.end():].strip()
            start = i if inline_prompt else prompt_start_before(i)
            markers.append({
                "line": start, "number_line": i, "points_line": i,
                "number": int(inline.group(2)), "points": int(inline.group(1)),
                "inline_prompt": inline_prompt
            })
            continue

        nmatch = NUMBER_RE.fullmatch(record["text"])
        if not nmatch:
            continue
        number = int(nmatch.group(1))
        if not 1 <= number <= 50:
            continue
        previous = lines[i - 1]["text"] if i else ""
        following = lines[i + 1]["text"] if i + 1 < len(lines) else ""

        # Sometimes the question text comes first, followed by its number and point marker.
        if point_re.match(following):
            pm = point_re.match(following)
            start = i - 1 if (previous.endswith("?") or prompt_starts.match(previous)) else prompt_start_before(i)
            markers.append({"line": start, "number_line": i, "points_line": i + 1, "number": number, "points": int(pm.group(1))})
            continue

        # A small number of source PDFs place the question number before
        # a multi-line prompt and the score marker after it. Enable this
        # layout only for the exam known to use it; elsewhere retain the
        # stricter same-baseline rule to avoid treating numbered lists as
        # question markers.
        search_offsets = range(2, 13) if allow_multiline_number_first else range(2, 7)
        for offset in search_offsets:
            j = i + offset
            if j >= len(lines):
                break
            pm = point_re.match(lines[j]["text"])
            if not pm:
                continue
            prompt_lines = [x["text"] for x in lines[i + 1:j]]
            prompt = " ".join(prompt_lines).strip()
            first_prompt = prompt_lines[0] if prompt_lines else ""
            has_question_prompt = (
                bool(prompt_starts.match(first_prompt))
                or bool(re.match(r"^(?:bij\s+(?:welke|welk|wat|wie|hoe)|met\s+welk)", first_prompt, re.I))
                or "?" in first_prompt
                or (allow_multiline_number_first and any("?" in x for x in prompt_lines))
            )
            same_baseline = abs(lines[j]["bbox"][1] - lines[i]["bbox"][1]) <= 8
            if prompt and has_question_prompt:
                markers.append({"line": i, "number_line": i, "points_line": j, "number": number, "points": int(pm.group(1))})
            break

    unique = []
    seen = set()
    for marker in sorted(markers, key=lambda x: x["line"]):
        if marker["number"] not in seen:
            unique.append(marker)
            seen.add(marker["number"])
    return unique

def parse_options(block_lines):
    """Parse sequential A-F choices, including multiple choices on one PDF line."""
    options = []
    current = None
    expected = "A"
    stop_starts = re.compile(
        r"^(let op|lees verder|einde|bronvermelding|de volgende|om uit te sluiten|"
        r"fokkers|afbeelding|tijdens|na afloop|hieronder staat|in het onderzoek|"
        r"de onderzoekers|vervolgens)", re.I
    )

    def begin_option(key, value=""):
        nonlocal current, expected
        if current is not None:
            options.append(current)
        current = {"key": key, "text": value.strip()}
        expected = chr(ord(key) + 1) if key < "F" else None

    for raw_line in block_lines:
        line = raw_line.strip()
        if not line:
            continue
        start_match = OPTION_RE.match(line)
        if start_match and start_match.group(1) == expected:
            begin_option(start_match.group(1))
            line = (start_match.group(2) or "").strip()
        elif current is None:
            continue

        if re.match(r"^\d+\s*p$", line, re.I) or HEADER_RE.match(line):
            break
        if len(options) >= 3 and current["text"] and stop_starts.match(line):
            break

        # A PDF text layer can put e.g. D ... E ... on one extracted line.
        remainder = line
        while expected and expected <= "F":
            inline = re.search(r"\s(" + re.escape(expected) + r")(?:\s+|$)", remainder)
            if not inline:
                break
            before = remainder[:inline.start()].strip()
            if before:
                current["text"] = (current["text"] + " " + before).strip()
            key = inline.group(1)
            remainder = remainder[inline.end():].strip()
            begin_option(key)
        if remainder:
            current["text"] = (current["text"] + " " + remainder).strip()

    if current is not None:
        options.append(current)

    keys = [option["key"] for option in options]
    if len(keys) < 3 or keys != list("ABCDEF"[:len(keys)]):
        compact = " ".join(block_lines)
        labels = re.search(r"\bA\s+B\s+C\s+D(?:\s+E)?(?:\s+F)?\b", compact)
        if not labels:
            return []
        keys = labels.group(0).split()
        return [{"key": key, "text": "Bekijk optie " + key + " in de oorspronkelijke afbeelding"} for key in keys]

    for option in options:
        if not option["text"]:
            option["text"] = "Bekijk optie " + option["key"] + " in de oorspronkelijke afbeelding"
    return options

def find_numbered_list_prompt(lines, context_indices, marker):
    """Find question-owned numbered statements before the printed score marker.

    PDF text extraction sometimes puts the item number on a separate line from
    its statement. Accept both layouts, and recognise the different lead-ins
    used by exam writers (not only sentences beginning with "Hieronder").
    """
    eligible = sorted(i for i in context_indices if i < marker["number_line"])
    lower_bound = max(0, marker["number_line"] - 48)
    candidates = [i for i in eligible if i >= lower_bound]

    def item_number(value):
        value = value.strip()
        match = re.match(r"^([1-4])(?:[.)]\\s*|\\s+)(.*)$", value)
        if match and match.group(2).strip():
            return int(match.group(1))
        if re.fullmatch(r"[1-4][.)]?", value):
            return int(value.rstrip(".)"))
        return None

    # Find a numbered sequence first. A number-only line may be followed by
    # its wrapped statement on the next physical PDF line.
    sequences = []
    for position, line_index in enumerate(candidates):
        if item_number(lines[line_index]["text"]) != 1:
            continue
        numbers = []
        last_number = 0
        for candidate_index in candidates[position:]:
            number = item_number(lines[candidate_index]["text"])
            if number is None:
                continue
            if number == last_number + 1:
                numbers.append(number)
                last_number = number
            elif number == 1 and not numbers:
                numbers = [1]
                last_number = 1
            elif number > last_number + 1:
                break
        if len(numbers) >= 2:
            sequences.append((line_index, numbers))

    if not sequences:
        return None

    # Prefer the nearest explicit lead-in immediately before the sequence.
    heading_re = re.compile(
        r"(?i)\\b(?:uitspraken?|situaties?|onderdelen|processen|stoffen|"
        r"kenmerken|gevolgen|conclusies|mogelijkheden|gegevens)\\b"
    )
    for first_item, _ in reversed(sequences):
        preceding = [i for i in candidates if i < first_item]
        for heading_index in reversed(preceding[-8:]):
            if heading_re.search(lines[heading_index]["text"]):
                return heading_index
    return None


def clean_context(lines):
    cleaned = []
    for line in lines:
        text = line.strip()
        if not text or HEADER_RE.match(text):
            continue
        if re.fullmatch(r"\d+\s*p", text, re.I) or NUMBER_RE.fullmatch(text):
            continue
        cleaned.append(text)
    return "\n".join(cleaned).strip()

def answer_from_cv(cv_text, qnum):
    # The official CV stores MCQ answers as e.g. "11  B  2".
    line_pattern = re.compile(rf"^\s*{qnum}\s+([A-F])\s+\d+\s*$")
    for line in cv_text.splitlines():
        match = line_pattern.match(line)
        if match:
            return match.group(1).upper()
    # Some layouts put the letter on the line immediately after the number.
    lines = cv_text.splitlines()
    for i, line in enumerate(lines[:-1]):
        if line.strip() == str(qnum):
            match = re.match(r"^\s*([A-F])\s+\d+\s*$", lines[i + 1])
            if match:
                return match.group(1).upper()
    return ""

def extract_exam(prefix, level, year, period, exam_rel, cv_rel):
    # Remaining multi-question pages have explicit context-start anchors.
    # Question 24 in VWO 2026-II starts at its own HAE context paragraph.
    # The selected same-page exceptions use exact context-start anchors.
    # Question 9 uses two precise context crops to exclude questions 7 and 8.
    # Keep each card's crop local to its context and question; never include prior question text.
    exam_path, cv_path = ROOT / exam_rel, ROOT / cv_rel
    if not exam_path.exists() or not cv_path.exists():
        raise FileNotFoundError(f"Missing source file: {exam_path if not exam_path.exists() else cv_path}")
    with fitz.open(cv_path) as cv_doc:
        cv_text = "\n".join(page.get_text("text", sort=True) for page in cv_doc)
    found = []
    open_found = []
    contexts = []
    heading_re = re.compile(r"^(?:vraag|antwoord|scores|afbeelding(?:\s+\d+)?|tabel(?:\s+\d+)?|grafiek(?:\s+\d+)?|legenda|lees verder|einde)$", re.I)
    with fitz.open(exam_path) as doc:
        for page_index, page in enumerate(doc):
            # Context is page-local. Never carry text from the preceding PDF page:
            # a new topic can begin at the top of every page, and stale context
            # was the cause of unrelated introductions appearing on later questions.
            lines = line_records(page)
            markers = find_markers(lines, allow_multiline_number_first=(prefix == "ha24t1" and page_index != 15))
            if prefix == "ha24t1" and page_index == 15:
                # The answer-key table on printed page 16 contains numbered
                # response rows that resemble question markers; only q31 is
                # an actual exam question on this page.
                markers = [m for m in markers if m["number"] not in {2, 3, 4, 5}]
            if prefix == "ha24t2" and page_index == 10:
                # The diagram/table on printed page 11 contains isolated
                # labels 4, 5 and 9 before question 24; they are not questions.
                markers = [m for m in markers if m["number"] not in {4, 5, 9}]
            if not markers:
                headings = [
                    j for j, line in enumerate(lines)
                    if (line["size"] >= 13 or (line["bold"] and line["size"] >= 10.5))
                    and len(line["text"]) < 90
                    and not HEADER_RE.match(line["text"])
                    and not heading_re.match(line["text"])
                    and not re.match(r"^\d+\s*p", line["text"], re.I)
                ]
                # Pages without questions can contain the start or continuation
                # of a context. It is deliberately not reused on another page:
                # the next page is segmented independently to avoid stale context.
                continue

            previous_ranges = []
            cursor = 0
            for idx, marker in enumerate(markers):
                start = marker["line"]
                end = markers[idx + 1]["line"] if idx + 1 < len(markers) else len(lines)
                headings = [
                    j for j in range(cursor, start)
                    if (lines[j]["size"] >= 13 or (lines[j]["bold"] and lines[j]["size"] >= 12.5))
                    and len(lines[j]["text"]) < 90
                    and not HEADER_RE.match(lines[j]["text"])
                    and not heading_re.match(lines[j]["text"])
                    and not re.match(r"^\d+\s*p", lines[j]["text"], re.I)
                ]
                if headings:
                    cursor = headings[-1]
                    active_context = []
                context_line_indices = [j for j in range(cursor, start) if not any(a <= j < b for a, b in previous_ranges)]
                # Move a lead-in plus its numbered statements out of general context.
                list_prompt_start = find_numbered_list_prompt(lines, context_line_indices, marker)
                if list_prompt_start is not None:
                    context_line_indices = [j for j in context_line_indices if j < list_prompt_start]
                context_lines = [lines[j]["text"] for j in context_line_indices]
                # Each question gets only the context physically preceding it on
                # this page (plus context continued between questions on this page).
                # Do not append prior-page context: that silently associates unrelated
                # topics with the current question.
                context = clean_context(context_lines)
                page_image_rects = [
                    rect for image_info in page.get_images(full=True)
                    for rect in page.get_image_rects(image_info[0])
                    if rect.y0 < lines[start]["bbox"][1]
                ]
                page_drawing_rects = [
                    drawing["rect"] for drawing in page.get_drawings()
                    if drawing["rect"].width > 8 and drawing["rect"].height > 8
                    and drawing["rect"].y0 < lines[start]["bbox"][1]
                ]
                context_y_candidates = [lines[j]["bbox"][1] for j in context_line_indices] + [rect.y0 for rect in page_image_rects + page_drawing_rects]
                context_y0 = (
                    max(0, min(context_y_candidates) - 5)
                    if context_y_candidates else max(0, lines[start]["bbox"][1] - 0.5)
                )

                # A few pages contain multiple questions within one large text
                # block. Anchor these cards to the actual context paragraph for
                # that question so earlier question prompts are not repeated.
                manual_context_anchors = {
                    ("ha24t2", 3): "De aanwezigheid van mestkevers in de mest",
                    ("ha24t2", 6): "Een infectie met nematoden is aan te tonen",
                    ("ha24t2", 7): "Helmer gaat in gesprek met veehouders",
                    ("vw24t2", 2): "Lange tijd werd aangenomen dat przewalskipaarden wilde paarden zijn",
                    ("ha25t1", 14): "Eileen komt in aanmerking",
                    ("ha25t1", 27): "Uit onderzoek bij zeehonden",
                    ("ha26t1", 5): "Een kwartier na afloop van de inspanning",
                    ("ha26t1", 8): "Bomen langs de beek zorgen voor schaduw",
                    ("ha26t1", 17): "Hieronder staat een beschrijving van het onderzoek",
                    ("vw25t1", 30): "In tabel 2 is de aminozuurvolgorde",
                    ("vw25t1", 32): "Als een mutatie tot gevolg heeft",
                    ("vw25t1", 33): "Een stof die Na+-kanaaltjes in C-sensorische neuronen blokkeert",
                    ("vw25t1", 15): "In Afrika veroorzaken droge perioden",
                    ("vw25t1", 16): "Doordat de nijlpaardenpopulatie",
                    ("vw25t1", 17): "Sommige wetenschappers denken",
                    ("vw25t1", 18): "Nijlpaarden worden ‘ecosystem engineers’ genoemd",
                    ("vw26t1", 2): "Bloedplaatjes ontstaan in het rode beenmerg",
                    ("vw26t1", 9): "Om het tekort aan bloedplaatjes op te vangen",
                    ("vw26t1", 10): "Uit het bloedonderzoek bleek",
                    ("vw26t2", 14): "De waterspreeuw is de enige zangvogel",
                    ("vw26t2", 24): "Als het darmslijmvlies is opgezwollen",
                    ("ha26t1", 23): "Bij monocultuur verbouwt een boer één gewas",
                    ("ha26t1", 43): "Door antistoffen te gebruiken in de behandeling van mastitis",
                    ("ha26t2", 7): "Het bleek worden is het gevolg van het samentrekken",
                    ("ha26t2", 10): "Destiny laat zien dat de zwarte mangrove",
                    ("vw26t2", 3): "Voor de aanmaak van de nepetalactonen",
                }
                base_context_line_indices = context_line_indices[:]
                anchored_context = False
                anchor_text = manual_context_anchors.get((prefix, marker["number"]))
                if anchor_text:
                    anchor_hits = page.search_for(anchor_text)
                    if anchor_hits:
                        anchor_y = min(rect.y0 for rect in anchor_hits)
                        context_line_indices = [
                            j for j, line in enumerate(lines)
                            if anchor_y - 1 <= line["bbox"][1] < lines[start]["bbox"][1]
                        ]
                        context = clean_context([lines[j]["text"] for j in context_line_indices])
                        context_y0 = max(0, anchor_y - 5)
                        anchored_context = True

                # A question can start very near the top of a PDF page. In
                # that case the default context margin must not begin below
                # the question itself, or the resulting image crop is empty.
                if not anchored_context:
                    context_y0 = min(context_y0, max(0, lines[start]["bbox"][1] - 0.5))

                footer_y = footer_boundary(page, lines)
                if prefix == "vw25t1" and marker["number"] in {14, 15, 16, 17, 18}:
                    # Shared context is stitched separately from page 8 and
                    # the continuation on page 9; keep these crops question-only.
                    context_y0 = max(0, lines[marker["number_line"]]["bbox"][1] - 0.5)
                    print(f"Question-only crop {prefix} question {marker['number']}: starts at printed question marker")

                excluded = {marker["number_line"], marker["points_line"]}
                block_text = []
                block_indices = []
                if marker.get("inline_prompt"):
                    block_text.append(marker["inline_prompt"])
                    block_indices.append(marker["number_line"])
                for j in range(start, end):
                    if j not in excluded and not HEADER_RE.match(lines[j]["text"]):
                        block_text.append(lines[j]["text"])
                        block_indices.append(j)

                options = parse_options(block_text)
                # Exam PDFs often place the next context paragraph immediately
                # after the final answer option. The old parser treated that
                # paragraph as a continuation of option D/E/F. Detect the first
                # clear vertical paragraph break after the final option and cut
                # the question block there. This applies to every exam/question,
                # not to a hand-picked question number.
                option_positions = [
                    i for i, value in enumerate(block_text)
                    if OPTION_RE.match(value.strip())
                ]
                if len(option_positions) >= 3:
                    last_option_pos = option_positions[-1]
                    previous_bottom = lines[block_indices[last_option_pos]]["bbox"][3]
                    for j in range(last_option_pos + 1, len(block_text)):
                        current_line = lines[block_indices[j]]
                        paragraph_gap = current_line["bbox"][1] - previous_bottom
                        if paragraph_gap > 8:
                            block_text = block_text[:j]
                            block_indices = block_indices[:j]
                            break
                        previous_bottom = max(previous_bottom, current_line["bbox"][3])
                    options = parse_options(block_text)

                if (prefix, marker["number"]) == ("vw26t1", 9):
                    # The six percentage choices are split across columns in
                    # the source PDF; keep each alternative separate.
                    options = [
                        {"key": "A", "text": "2,6%"},
                        {"key": "B", "text": "4,0%"},
                        {"key": "C", "text": "16%"},
                        {"key": "D", "text": "27%"},
                        {"key": "E", "text": "71%"},
                        {"key": "F", "text": "84%"},
                    ]
                if (prefix, marker["number"]) == ("vw26t1", 22):
                    options = [
                        {"key": "A", "text": "samentrekken van de slagaderwand; diastolische druk"},
                        {"key": "B", "text": "samentrekken van de slagaderwand; systolische druk"},
                        {"key": "C", "text": "uitrekken van de slagaderwand; diastolische druk"},
                        {"key": "D", "text": "uitrekken van de slagaderwand; systolische druk"},
                    ]
                if (prefix, marker["number"]) == ("ha24t1", 9):
                    options = [
                        {"key": "A", "text": "met een lysosoom"},
                        {"key": "B", "text": "met een mitochondrium"},
                        {"key": "C", "text": "met een ribosoom"},
                        {"key": "D", "text": "met het endoplasmatisch reticulum met het golgi-systeem"},
                    ]

                first_option = next((i for i, x in enumerate(block_text) if OPTION_RE.match(x.strip())), len(block_text))
                selected_prompt = "\n".join(x for x in block_text[:first_option] if x.strip()).strip()
                if not selected_prompt:
                    selected_prompt = "\n".join(x for x in block_text if x.strip()).strip()

                # Determine where the question itself ends so later context can be
                # carried forward without carrying the previous question into the next card.
                if options and first_option < len(block_text):
                    option_positions = [i for i, x in enumerate(block_text) if OPTION_RE.match(x.strip())]
                    last_option = option_positions[-1]
                    end_pos = last_option
                    previous_bottom = lines[block_indices[last_option]]["bbox"][3]
                    for j in range(last_option + 1, min(len(block_text), last_option + 4)):
                        current_line = lines[block_indices[j]]
                        paragraph_gap = current_line["bbox"][1] - previous_bottom
                        if paragraph_gap > 10:
                            break
                        if re.match(r"^\d+\s*p$", block_text[j].strip(), re.I) or HEADER_RE.match(block_text[j].strip()):
                            break
                        end_pos = j
                        previous_bottom = max(previous_bottom, current_line["bbox"][3])
                    question_end_line = block_indices[end_pos]
                elif start < marker["number_line"]:
                    question_end_line = marker["points_line"]
                else:
                    # Open questions do not have A-D options to delimit them.
                    # Do not consume every line up to the next question marker:
                    # a new boxed/context paragraph can begin in between (e.g.
                    # Havo 2025-I question 13 followed by the transplant context
                    # for question 14). Stop at the first clear paragraph break
                    # after the question prompt has begun.
                    question_end_line = end - 1
                    previous_bottom = lines[start]["bbox"][3]
                    prompt_seen = False
                    for j in range(start + 1, end):
                        gap = lines[j]["bbox"][1] - previous_bottom
                        if prompt_seen and gap > 10:
                            question_end_line = j - 1
                            break
                        if j not in {marker["number_line"], marker["points_line"]}:
                            prompt_seen = True
                        previous_bottom = max(previous_bottom, lines[j]["bbox"][3])
                question_end_line = max(start, min(question_end_line, end - 1))

                selected_context_page = SELECTED_CONTEXT_PAGES.get((prefix, marker["number"]))
                context_record = None
                if selected_context_page is None or page_index + 1 == selected_context_page:
                    context_image = f"question-{prefix}-{marker['number']}.jpg"
                    question_start_line = list_prompt_start if list_prompt_start is not None else start
                    question_top = min(
                        max(0, lines[question_start_line]["bbox"][1] - 1), page.rect.height - 55
                    )
                    # Havo 2025-I question 26 has three numbered statements
                    # immediately before the printed question marker. They are
                    # question material, not general context: start the separate
                    # question crop at statement 1 so all three remain visible.
                    if prefix == "ha25t1" and marker["number"] == 26:
                        statement_start = page.search_for("Hieronder staan drie uitspraken.")
                        if not statement_start:
                            raise RuntimeError("Could not locate the Havo 2025-I question 26 lead-in")
                        question_top = max(0, min(rect.y0 for rect in statement_start) - 2)
                    question_y1 = min(
                        page.rect.height - 15,
                        max(question_top + 40, min(footer_y, lines[question_end_line]["bbox"][3] + BOTTOM_TEXT_PADDING)),
                    )
                    # The Havo 2025-I question 29 detector previously retained
                    # an excessive blank strip below the actual prompt. Use the
                    # printed final sentence as the precise lower boundary.
                    if prefix == "ha25t1" and marker["number"] == 29:
                        final_prompt = page.search_for("Noteer de naam van dit eiwit.")
                        if not final_prompt:
                            raise RuntimeError("Could not locate the final prompt line for Havo 2025-I question 29")
                        question_y1 = min(footer_y, max(rect.y1 for rect in final_prompt) + 6)
                    # When a numbered statement list belongs to the question,
                    # the context image must stop immediately before its lead-in.
                    # Removing OCR lines alone is insufficient: the PDF crop would
                    # otherwise still visually include the statements.
                    context_bottom = question_y1
                    if list_prompt_start is not None:
                        context_bottom = max(
                            context_y0 + 20,
                            min(context_bottom, lines[list_prompt_start]["bbox"][1] - 2),
                        )
                    try:
                        save_page_crop(
                            page,
                            fitz.Rect(0, context_y0, page.rect.width, context_bottom),
                            OUT / context_image,
                            lines,
                            previous_ranges,
                        )
                    except RuntimeError:
                        # Preserve the independently rendered context fragment.
                        page.get_pixmap(
                            matrix=fitz.Matrix(1.8, 1.8),
                            clip=fitz.Rect(0, context_y0, page.rect.width, context_bottom),
                            alpha=False,
                        ).save(OUT / context_image)
                    context_record = {"level": level, "year": year, "period": period, "n": marker["number"], "page": page_index + 1, "image": f"exam-snippets/{context_image}"}
                    if (prefix, marker["number"]) not in {("ha25t2", 9), ("vw25t1", 14)}:
                        # Use the printed score/question marker as the
                        # lower boundary for open-question context fragments too.
                        context_question_top = max(
                            0, lines[list_prompt_start if list_prompt_start is not None else marker["number_line"]]["bbox"][1]
                        )
                        context_start_anchors = {
                            15: "In Afrika veroorzaken droge perioden",
                            16: "Doordat de nijlpaardenpopulatie",
                            17: "Sommige wetenschappers denken",
                            18: "Nijlpaarden worden",
                        }
                        context_end_anchors = {
                            15: "biotische factoren.",
                            16: "populaties in Afrika.",
                            17: "aparte soort.",
                            18: "climaxsoorten beïnvloeden.",
                        }
                        context_paths = context_image_fragments(
                            page, lines, context_line_indices, prefix, marker["number"],
                            context_question_top, footer_y, previous_ranges,
                            end_anchor=(
                                context_end_anchors.get(marker["number"])
                                if prefix == "vw25t1" else None
                            ),
                            start_anchor=(
                                context_start_anchors.get(marker["number"])
                                if prefix == "vw25t1" else None
                            ),
                        )
                        if prefix == "ha25t1" and marker["number"] == 32:
                            # Question 32 continues the context introduced with
                            # question 31; retain that first context fragment.
                            previous_context = "exam-snippets/context-ha25t1-q31-complete.jpg"
                            if not (ROOT / previous_context).is_file():
                                raise RuntimeError("Missing Havo 2025-I question 31 context for question 32")
                            context_paths = [previous_context, *context_paths]
                        if not context_paths:
                            if (prefix, marker["number"]) in {
                                ("vw25t1", 15), ("vw25t1", 16),
                                ("vw25t1", 17), ("vw25t1", 18),
                            }:
                                raise RuntimeError(
                                    f"Question-specific context crop failed for {prefix} "
                                    f"question {marker['number']}; refusing to substitute "
                                    "preceding question contexts."
                                )
                            context_paths = fallback_context_fragment(
                                page, lines, prefix, marker["number"], question_top, previous_ranges,
                            )
                        question_name = f"question-{prefix}-{marker['number']}-only.jpg"
                        if question_y1 > question_top + 2:
                            page.get_pixmap(
                                matrix=fitz.Matrix(1.8, 1.8),
                                clip=fitz.Rect(0, question_top, page.rect.width, question_y1),
                                alpha=False,
                            ).save(OUT / question_name)
                            trim_question_bottom_rule(OUT / question_name)
                            context_paths.append(f"exam-snippets/{question_name}")

                        # Havo 2025-I q26: the numbered statements are part of
                        # the question, but are printed above its score/number
                        # marker. Build the question crop from the exact first
                        # statement through the exact final instruction line;
                        # the general context crop ends before the statements.
                        if prefix == "ha25t1" and marker["number"] == 26:
                            statement_hits = page.search_for("Door het inhouden van de adem")
                            heading_hits = page.search_for("Hieronder staan drie uitspraken.")
                            prompt_hits = page.search_for("bijbehorende uitspraak juist of onjuist is.")
                            if not statement_hits or not heading_hits or not prompt_hits:
                                raise RuntimeError(
                                    "Could not locate all Havo 2025-I q26 statements and final prompt"
                                )
                            statement_top = max(0, min(hit.y0 for hit in heading_hits) - 3)
                            prompt_bottom = min(
                                page.rect.height - 12,
                                max(hit.y1 for hit in prompt_hits) + 6,
                            )
                            if prompt_bottom <= statement_top + 100:
                                raise RuntimeError(
                                    f"Invalid Havo 2025-I q26 statement crop: "
                                    f"top={statement_top}, bottom={prompt_bottom}"
                                )
                            page.get_pixmap(
                                matrix=fitz.Matrix(1.8, 1.8),
                                clip=fitz.Rect(0, statement_top, page.rect.width, prompt_bottom),
                                alpha=False,
                            ).save(OUT / question_name)
                            question_crop = Image.open(OUT / question_name)
                            try:
                                if question_crop.height < 180:
                                    raise RuntimeError(
                                        f"Havo 2025-I q26 crop omits its three statements: "
                                        f"{question_crop.width}x{question_crop.height}"
                                    )
                            finally:
                                question_crop.close()
                        if context_paths:
                            context_record["images"] = context_paths
                    if (prefix, marker["number"]) == ("ha25t2", 9):
                        # Keep the initial pedigree context and the later inbreeding
                        # paragraph, but never include the intervening questions 7 and 8.
                        intro_hits = page.search_for("Freek wil graag zwarte kippen gaan fokken")
                        q7_marker = next((m for m in markers if m["number"] == 7), None)
                        inbreeding_hits = page.search_for("Fokkers kruisen vaker")
                        inbreeding_end_hits = page.search_for("tot uiting komen.")
                        q9_prompt_hits = page.search_for("Verklaar hoe inteelt leidt")
                        if not intro_hits or not q7_marker or not inbreeding_hits or not inbreeding_end_hits or not q9_prompt_hits:
                            raise RuntimeError("Could not isolate the Havo 2025-II question 9 context fragments")
                        q7_y = lines[q7_marker["line"]]["bbox"][1]
                        q9_y = min(rect.y0 for rect in q9_prompt_hits)
                        intro_y0 = max(0, min(rect.y0 for rect in intro_hits) - 5)
                        inbreeding_y0 = max(0, min(rect.y0 for rect in inbreeding_hits) - 5)
                        inbreeding_y1 = min(page.rect.height, max(rect.y1 for rect in inbreeding_end_hits) + 8)
                        question_y1 = min(footer_y, lines[question_end_line]["bbox"][3] + max(BOTTOM_TEXT_PADDING, 4))
                        intro_name = "context-ha25t2-q9-intro.jpg"
                        inbreeding_name = "context-ha25t2-q9-inbreeding.jpg"
                        page.get_pixmap(matrix=fitz.Matrix(1.8, 1.8), clip=fitz.Rect(0, intro_y0, page.rect.width, min(q7_y - 5, footer_y)), alpha=False).save(OUT / intro_name)
                        page.get_pixmap(matrix=fitz.Matrix(1.8, 1.8), clip=fitz.Rect(0, inbreeding_y0, page.rect.width, inbreeding_y1), alpha=False).save(OUT / inbreeding_name)
                        page.get_pixmap(matrix=fitz.Matrix(1.8, 1.8), clip=fitz.Rect(0, max(0, q9_y - 0.5), page.rect.width, min(question_y1, footer_y)), alpha=False).save(OUT / context_image)
                        context_record["images"] = [
                            f"exam-snippets/{intro_name}",
                            f"exam-snippets/{inbreeding_name}",
                            f"exam-snippets/{context_image}",
                        ]
                    if (prefix, marker["number"]) in {("vw25t1", 14), ("vw25t1", 15), ("vw25t1", 16), ("vw25t1", 17), ("vw25t1", 18)}:
                        context_record["images"] = ["exam-snippets/vw25-t1-hippo-context.jpg"]
                        if marker["number"] == 14:
                            context_record["images"].append("exam-snippets/vw25-t1-hippo-q14-context.jpg")
                            context_record["images"].append(f"exam-snippets/{context_image}")
                        elif marker["number"] in {15, 16, 17, 18}:
                            # context_paths already contains the individual context
                            # and the question-only crop; do not append context_image
                            # again, which duplicates the question in the rendered card.
                            context_record["images"].extend(context_paths)
                        else:
                            context_record["images"].append(f"exam-snippets/{context_image}")
                    contexts.append(context_record)

                false_positive_open_questions = {
                    
                }
                if (prefix, marker["number"]) in false_positive_open_questions:
                    previous_ranges.append((start, question_end_line + 1))
                    cursor = question_end_line + 1
                    continue
                if not options:
                    prompt_start_line = list_prompt_start if list_prompt_start is not None else start
                    selected_prompt = "\n".join(
                        lines[j]["text"] for j in range(prompt_start_line, question_end_line + 1)
                        if j not in {marker["number_line"], marker["points_line"]}
                        and not HEADER_RE.match(lines[j]["text"])
                    ).strip()
                    if prefix == "ha25t1" and marker["number"] == 26:
                        # The source PDF places the heading and three numbered
                        # statements above the printed score/question marker.
                        # Keep the shared context clean and put the lead-in in
                        # the question text; the dedicated crop contains all
                        # three statements and the final instruction.
                        context = re.sub(
                            r"(?is)\s*Hieronder\s+staan\s+drie\s+uitspraken\b.*$",
                            "",
                            context,
                        ).strip()
                        selected_prompt = "Hieronder staan drie uitspraken.\n" + selected_prompt
                    if context_record is None and selected_context_page is not None:
                        previous_ranges.append((start, question_end_line + 1))
                        cursor = question_end_line + 1
                        continue
                    if context_record is None:
                        raise RuntimeError(f"No image/context record for open question {prefix} {marker['number']}")
                    open_found.append({
                        "id": f"{prefix}-open-{marker['number']}",
                        "level": level, "year": year, "period": period,
                        "n": marker["number"], "points": marker["points"],
                        "page": page_index + 1,
                        "theme": "Nog te rubriceren", "concept": "Open vraag",
                        "end": "Nog te rubriceren",
                        "focus": "Open vraag uit het officiële centraal examen.",
                        "source": context or "Gebruik de context en gegevens in de oorspronkelijke examenopgave.",
                        "q": selected_prompt,
                        "image": context_record["image"],
                        "images": context_record.get("images", []),
                        "pdf": exam_rel, "cv": cv_rel, "questionType": "open"
                    })
                    previous_ranges.append((start, question_end_line + 1))
                    cursor = question_end_line + 1
                    continue

                correct = answer_from_cv(cv_text, marker["number"])
                option_keys = [o["key"] for o in options]
                required_keys = "ABCDEF"[:max(len(option_keys), "ABCDEF".find(correct) + 1 if correct else len(option_keys))]
                if (prefix, marker["number"]) == ("vw25t2", 22):
                    required_keys = "ABCDEF"
                options_by_key = {o["key"]: o for o in options}
                options = [{"key": key, "text": options_by_key.get(key, {}).get("text", "")} for key in required_keys]

                # Full-width page strip containing context and question.
                y0 = min(context_y0, max(0, lines[start]["bbox"][1] - 5))
                y1 = min(
                    footer_y,
                    max(
                        lines[question_end_line]["bbox"][3] + BOTTOM_TEXT_PADDING,
                        lines[start]["bbox"][3] + BOTTOM_TEXT_PADDING,
                        y0 + 2,
                    ),
                )
                if (prefix, marker["number"]) == ("vw26t1", 22):
                    # The final option sits below the text block detected by
                    # the generic parser; include the complete answer table.
                    systolic_hits = page.search_for("systolische druk")
                    if len(systolic_hits) < 2:
                        raise RuntimeError("Could not locate all options for VWO 2026-I question 22")
                    y1 = min(footer_y, max(y1, max(rect.y1 for rect in systolic_hits) + BOTTOM_TEXT_PADDING))
                crop = fitz.Rect(0, y0, page.rect.width, y1)
                qid = f"{prefix}-mcq-{marker['number']}"
                image_name = f"mcq-{qid}.jpg"
                save_page_crop(page, crop, OUT / image_name, lines, previous_ranges)
                mcq_images = None
                if (prefix, marker["number"]) == ("vw26t1", 9):
                    if page_index == 0:
                        raise RuntimeError("VWO 2026-I question 9 has no preceding context page")
                    previous_page = doc[page_index - 1]
                    previous_lines = line_records(previous_page)
                    previous_markers = find_markers(previous_lines)
                    q5_marker = next((m for m in previous_markers if m["number"] == 5), None)
                    intro_hits = previous_page.search_for("Nadat andere oorzaken werden uitgesloten")
                    if not q5_marker or not intro_hits:
                        raise RuntimeError("Could not isolate the HPA context table for VWO 2026-I question 9")
                    context_top = max(0, min(rect.y0 for rect in intro_hits) - 5)
                    context_bottom = max(context_top + 20, previous_lines[q5_marker["line"]]["bbox"][1] - 2)
                    context_name = "context-vw26t1-q9-table.jpg"
                    previous_page.get_pixmap(
                        matrix=fitz.Matrix(1.8, 1.8),
                        clip=fitz.Rect(0, context_top, previous_page.rect.width, context_bottom),
                        alpha=False,
                    ).save(OUT / context_name)
                    mcq_images = [f"exam-snippets/{context_name}", f"exam-snippets/{image_name}"]
                if (prefix, marker["number"]) == ("vw26t2", 37):
                    # The model and introductory context belong to question 37;
                    # questions 36's statements must not be repeated in its card.
                    intro_hits = page.search_for("Onderzoekers wilden weten")
                    context_end_hits = page.search_for("Hieronder staan gegevens van de flamingosoort")
                    q37_hits = page.search_for("Hoe groot is volgens het model")
                    if not intro_hits or not context_end_hits or not q37_hits:
                        raise RuntimeError("Could not isolate VWO 2026-II question 37 context")
                    context_y0 = max(0, min(rect.y0 for rect in intro_hits) - 5)
                    context_y1 = min(page.rect.height, min(rect.y0 for rect in context_end_hits) - 2)
                    question_y0 = max(0, min(rect.y0 for rect in q37_hits) - 0.5)
                    question_y1 = min(page.rect.height, lines[question_end_line]["bbox"][3] + BOTTOM_TEXT_PADDING)
                    context_name = "context-vw26t2-q37-model.jpg"
                    question_name = "question-vw26t2-37.jpg"
                    page.get_pixmap(matrix=fitz.Matrix(1.8, 1.8), clip=fitz.Rect(0, context_y0, page.rect.width, context_y1), alpha=False).save(OUT / context_name)
                    page.get_pixmap(matrix=fitz.Matrix(1.8, 1.8), clip=fitz.Rect(0, question_y0, page.rect.width, question_y1), alpha=False).save(OUT / question_name)
                    image_name = question_name
                    mcq_images = [f"exam-snippets/{context_name}", f"exam-snippets/{question_name}"]

                # Apply the same context/question separation to every MCQ, not
                # only to the hand-picked open-question context inventory.
                # Context paragraphs are independent full-width strips; the
                # question and answer options are always rendered separately.
                if mcq_images is None:
                    question_top = max(0, lines[start]["bbox"][1] - 1)
                    question_y1 = min(footer_y, lines[question_end_line]["bbox"][3] + BOTTOM_TEXT_PADDING)
                    # When the generic end-line detector misses a compact or
                    # table-style prompt, use the parsed answer-option rows as
                    # a second boundary so the final option is never clipped.
                    option_bottoms = [
                        lines[i]["bbox"][3]
                        for i in range(start, min(end, len(lines)))
                        if OPTION_RE.match(lines[i]["text"])
                    ]
                    if option_bottoms:
                        question_y1 = min(
                            footer_y,
                            max(question_y1, max(option_bottoms) + BOTTOM_TEXT_PADDING),
                        )
                    # The context must stop above the printed score/question
                    # marker, not above marker["line"]: that can be the prompt
                    # line itself and let the top of the question leak into the
                    # context card. Keep a visible lower margin as well.
                    context_question_top = max(
                        0, lines[marker["number_line"]]["bbox"][1]
                    )
                    context_paths = context_image_fragments(
                        page, lines, context_line_indices, prefix,
                        marker["number"], context_question_top, footer_y, previous_ranges,
                    )
                    if not context_paths:
                        context_paths = fallback_context_fragment(
                            page, lines, prefix, marker["number"], question_top, previous_ranges,
                        )
                    question_name = f"question-{prefix}-{marker['number']}-only.jpg"
                    if question_y1 > question_top + 2:
                        page.get_pixmap(
                            matrix=fitz.Matrix(1.8, 1.8),
                            clip=fitz.Rect(0, question_top, page.rect.width, question_y1),
                            alpha=False,
                        ).save(OUT / question_name)
                        context_paths.append(f"exam-snippets/{question_name}")
                    else:
                        # Compact prompts and table-style questions can defeat
                        # line-end detection. Keep a bounded question-only crop
                        # so context is not duplicated and the prompt is not cut.
                        fallback_question_bottom = min(
                            footer_y,
                            max(question_y1, question_top + 65),
                        )
                        if fallback_question_bottom > question_top + 2:
                            page.get_pixmap(
                                matrix=fitz.Matrix(1.8, 1.8),
                                clip=fitz.Rect(0, question_top, page.rect.width, fallback_question_bottom),
                                alpha=False,
                            ).save(OUT / question_name)
                            context_paths.append(f"exam-snippets/{question_name}")
                        else:
                            # Last-resort: preserve the original crop rather
                            # than silently dropping the question altogether.
                            context_paths.append(f"exam-snippets/{image_name}")
                    mcq_images = context_paths or [f"exam-snippets/{image_name}"]

                prompt = "\n".join(x for x in block_text[:first_option] if x.strip()).strip()
                if not prompt:
                    prompt = "\n".join(x for x in block_text if x.strip()).strip()
                found.append({
                    "id": qid,
                    "level": level,
                    "year": year,
                    "period": period,
                    "n": marker["number"],
                    "points": marker["points"],
                    "page": page_index + 1,
                    "theme": "Meerkeuzevragen",
                    "concept": "Meerkeuze",
                    "end": "Nog te rubriceren",
                    "focus": "Meerkeuzevraag uit het officiële centraal examen.",
                    "source": context or "Gebruik de context en gegevens in de oorspronkelijke examenopgave.",
                    "q": prompt,
                    "options": options,
                    "correct": correct,
                    "image": f"exam-snippets/{image_name}",
                    **({"images": mcq_images} if mcq_images else {}),
                    "pdf": exam_rel,
                    "cv": cv_rel,
                    "questionType": "mcq",
                })
                previous_ranges.append((start, question_end_line + 1))
                cursor = question_end_line + 1
    return found, contexts, open_found


all_questions = []
all_open_questions = []
all_contexts = []
for exam in EXAMS:
    items, contexts, open_items = extract_exam(*exam)
    all_questions.extend(items)
    all_open_questions.extend(open_items)
    all_contexts.extend(contexts)
    print(f"{exam[0]}: {len(items)} meerkeuzevragen, {len(open_items)} open vragen, {len(contexts)} vraagcontexten")
# Question 40 in VWO 2025 time slot 2 uses a table layout that PyMuPDF
# does not expose as ordinary A-D text blocks; add it from the official page.
if not any(q["id"] == "vw25t2-mcq-40" for q in all_questions):
    pdf_rel = "examens/vw-1018-a-25-2-o.pdf"
    with fitz.open(ROOT / pdf_rel) as doc:
        page = doc[18]  # printed page 19 of the exam
        start_hits = page.search_for("Op welk type eiland")
        end_hits = page.search_for("klein veraf")
        if not start_hits or not end_hits:
            raise RuntimeError("Could not locate VWO 2025 time slot 2 question 40 for its image crop")
        y0 = max(0, min(r.y0 for r in start_hits) - 5)
        y1 = min(page.rect.height, max(r.y1 for r in end_hits) + 6)
        image_name = "mcq-vw25t2-mcq-40.jpg"
        page.get_pixmap(
            matrix=fitz.Matrix(1.8, 1.8),
            clip=fitz.Rect(0, y0, page.rect.width, y1),
            alpha=False,
        ).save(OUT / image_name)
    all_questions.append({
        "id": "vw25t2-mcq-40",
        "level": "Vwo",
        "year": "2025",
        "period": "2",
        "n": 40,
        "points": 2,
        "page": 19,
        "theme": "Meerkeuzevragen",
        "concept": "Meerkeuze",
        "end": "Nog te rubriceren",
        "focus": "Meerkeuzevraag over de eilandtheorie van McArthur en Wilson.",
        "source": "De verdwerging van grote zoogdieren op een gekoloniseerd eiland is mede te verklaren met de eilandtheorie van McArthur en Wilson. Een kleiner aantal soorten op een eiland maakt de kans groter dat predatoren afwezig zijn. Grote zoogdiersoorten kunnen dan verdwergen.",
        "q": "Op welk type eiland zal het aantal soorten het kleinst zijn volgens de eilandtheorie van McArthur en Wilson?",
        "options": [
            {"key": "A", "text": "groot, dichtbij"},
            {"key": "B", "text": "groot, veraf"},
            {"key": "C", "text": "klein, dichtbij"},
            {"key": "D", "text": "klein, veraf"},
        ],
        "correct": "D",
        "image": "exam-snippets/mcq-vw25t2-mcq-40.jpg",
        "pdf": pdf_rel,
        "cv": "examens/vw-1018-a-25-2-c.pdf",
        "questionType": "mcq",
    })

# Hard coverage gate: each numbered exam question must appear exactly once.
for exam in EXAMS:
    exam_key, level, year, period, exam_rel, cv_rel = exam
    with fitz.open(ROOT / exam_rel) as source_doc:
        detected = set()
        for page_index, page in enumerate(source_doc):
            page_markers = find_markers(
                line_records(page), allow_multiline_number_first=(exam_key == "ha24t1" and page_index != 15)
            )
            if exam_key == "ha24t1" and page_index == 15:
                page_markers = [m for m in page_markers if m["number"] not in {2, 3, 4, 5}]
            if exam_key == "ha24t2" and page_index == 10:
                page_markers = [m for m in page_markers if m["number"] not in {4, 5, 9}]
            detected.update(marker["number"] for marker in page_markers)
    represented = [
        q for q in all_questions + all_open_questions
        if q["level"] == level and q["year"] == year and q["period"] == period
    ]
    represented_numbers = [q["n"] for q in represented]
    expected = set(range(1, max(detected or {0}) + 1))
    missing = sorted(expected - set(represented_numbers))
    duplicates = sorted(n for n in set(represented_numbers) if represented_numbers.count(n) > 1)
    if missing or duplicates:
        details = {}
        with fitz.open(ROOT / exam_rel) as source_doc:
            for page_index, page in enumerate(source_doc):
                page_lines = line_records(page)
                for marker in find_markers(page_lines, allow_multiline_number_first=(exam_key == "ha24t1")):
                    if marker["number"] in duplicates or marker["number"] in missing:
                        lo = max(0, marker["line"] - 2)
                        hi = min(len(page_lines), marker["line"] + 5)
                        details.setdefault(marker["number"], []).append({
                            "page": page_index + 1,
                            "lines": [x["text"] for x in page_lines[lo:hi]]
                        })
        if missing:
            missing_text = {}
            with fitz.open(ROOT / exam_rel) as source_doc:
                for page_index, page in enumerate(source_doc):
                    page_lines = line_records(page)
                    for line_index, line in enumerate(page_lines):
                        if NUMBER_RE.fullmatch(line["text"]) and int(line["text"]) in missing:
                            lo = max(0, line_index - 3)
                            hi = min(len(page_lines), line_index + 12)
                            missing_text.setdefault(int(line["text"]), []).append({
                                "page": page_index + 1,
                                "lines": [x["text"] for x in page_lines[lo:hi]]
                            })
            print(f"Missing-number source lines for {exam_key}: {missing_text}")
        print(f"Question marker diagnostics for {exam_key}: {details}")
        raise RuntimeError(
            f"Incomplete or duplicate question inventory for {exam_key}: "
            f"missing={missing}, duplicates={duplicates}, detected={sorted(detected)}"
        )
if len(EXAMS) != 12:
    raise RuntimeError(f"Expected all 12 Havo/Vwo exams from 2024-2026, found {len(EXAMS)}")

attach_appendix_links(all_questions)
attach_appendix_links(all_open_questions)

all_questions.sort(key=lambda q: (int(q["year"]), int(q["period"]), int(q["n"]), q["level"]))
all_open_questions.sort(key=lambda q: (int(q["year"]), int(q["period"]), int(q["n"]), q["level"]))

missing = [q["id"] for q in all_questions if not q["correct"]]
print(f"Totaal: {len(all_questions)} meerkeuzevragen; zonder automatisch gevonden antwoord: {len(missing)}")
if missing:
    print("Controle nodig voor antwoorden:", ", ".join(missing))
(ROOT / "exam-mcq.json").write_text(json.dumps(all_questions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
(ROOT / "exam-open.json").write_text(json.dumps(all_open_questions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
context_by_key = {}
for item in all_contexts:
    context_by_key.setdefault((item["level"], item["year"], item["period"], item["n"]), item)
all_contexts = list(context_by_key.values())
# Build a single complete preview image for every question card. Some clients
# display only the primary "image" field; previously that could show the question
# crop while silently omitting its context images. Keep the separate "images"
# array as well, but make the primary image a vertically stitched context+question.
def trim_all_question_images():
    """Apply the separator-edge cleanup to every generated question crop."""
    for image_path in OUT.glob("question-*.jpg"):
        trim_question_bottom_rule(image_path)


def stitch_question_images(record, fallback_prefix):
    image_paths = record.get("images") or ([record["image"]] if record.get("image") else [])
    missing = [path for path in image_paths if not (ROOT / path).exists()]
    if missing:
        raise RuntimeError(f"Missing source images for {record.get('id', record.get('n'))}: {missing}")
    if not image_paths:
        raise RuntimeError(f"No source images found for {record.get('id', record.get('n'))}")
    opened = [Image.open(ROOT / path).convert("RGB") for path in image_paths]
    width = max(image.width for image in opened)
    height = sum(image.height for image in opened) + 12 * (len(opened) - 1)
    combined = Image.new("RGB", (width, height), "white")
    y = 0
    for image in opened:
        combined.paste(image, (0, y))
        y += image.height + 12
    key = record.get("id") or f"{record['level'].lower()}-{record['year']}-t{record['period']}-q{record['n']}"
    output_name = f"{fallback_prefix}-{key}.jpg"
    combined.save(OUT / output_name, quality=94)
    record["image"] = f"exam-snippets/{output_name}"
    for image in opened:
        image.close()

trim_all_question_images()

# Apply the same context-first presentation to every MCQ and every selected
# open-question context, rather than relying on the frontend to render arrays.
for record in all_questions:
    if record.get("images"):
        stitch_question_images(record, "complete")
for record in all_contexts:
    if record.get("images"):
        stitch_question_images(record, "complete")
for record in all_open_questions:
    if record.get("images"):
        stitch_question_images(record, "complete")

# Some legacy full-question crops are emitted by the selected-fragment pass;
# run a final cleanup after every source and composite image has been created.
trim_all_question_images()

# Context records retain their separate image list for clients that support it;
# the primary image now always contains the full context followed by the question.
(ROOT / "exam-mcq.json").write_text(json.dumps(all_questions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
context_by_key = {}
for item in all_contexts:
    context_by_key.setdefault((item["level"], item["year"], item["period"], item["n"]), item)
all_contexts = list(context_by_key.values())
(ROOT / "exam-contexts.json").write_text(json.dumps(all_contexts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
(ROOT / "exam-open.json").write_text(json.dumps(all_open_questions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Geschreven: {len(all_questions)} meerkeuzevragen en {len(all_open_questions)} open vragen uit {len(EXAMS)} examens.")
