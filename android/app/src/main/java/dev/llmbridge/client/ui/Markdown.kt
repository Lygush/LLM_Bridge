package dev.llmbridge.client.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.LinkAnnotation
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextLinkStyles
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.withLink
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp

// =================================================================== разбор

sealed interface MdBlock
data class MdPara(val text: String) : MdBlock
data class MdHeading(val level: Int, val text: String) : MdBlock
data class MdCode(val lang: String, val code: String) : MdBlock
data class MdQuote(val text: String) : MdBlock
data class MdItem(val level: Int, val marker: String, val text: String)
data class MdList(val items: List<MdItem>) : MdBlock
data class MdTable(val header: List<String>, val rows: List<List<String>>) : MdBlock
data object MdRule : MdBlock

private val HEADING = Regex("""^(#{1,6})\s+(.*?)\s*#*\s*$""")
private val RULE = Regex("""^\s*([-*_])(\s*\1){2,}\s*$""")
private val QUOTE = Regex("""^\s*>\s?(.*)$""")
private val ITEM = Regex("""^(\s*)([-*+]|\d{1,3}[.)])\s+(.*)$""")
private val TABLE_SEP = Regex("""^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$""")

private fun cells(line: String): List<String> =
    line.trim().removePrefix("|").removeSuffix("|").split("|").map { it.trim() }

/** Разбор markdown на блоки. Терпим к незаконченному тексту (идёт генерация). */
fun parseMarkdown(src: String): List<MdBlock> {
    val lines = src.replace("\r\n", "\n").split("\n")
    val out = mutableListOf<MdBlock>()
    val para = StringBuilder()
    fun flush() {
        if (para.isNotBlank()) out.add(MdPara(para.toString().trim('\n')))
        para.clear()
    }
    var i = 0
    while (i < lines.size) {
        val line = lines[i]
        val t = line.trimStart()
        when {
            t.startsWith("```") || t.startsWith("~~~") -> {
                flush()
                val fence = t.take(3)
                val lang = t.drop(3).trim()
                val code = StringBuilder()
                i++
                while (i < lines.size && !lines[i].trimStart().startsWith(fence)) {
                    if (code.isNotEmpty()) code.append('\n')
                    code.append(lines[i])
                    i++
                }
                out.add(MdCode(lang, code.toString()))
            }
            line.isBlank() -> flush()
            HEADING.matches(t) -> {
                flush()
                val m = HEADING.find(t)!!
                out.add(MdHeading(m.groupValues[1].length, m.groupValues[2]))
            }
            RULE.matches(line) -> { flush(); out.add(MdRule) }
            QUOTE.matches(line) -> {
                flush()
                val q = StringBuilder()
                while (i < lines.size && QUOTE.matches(lines[i])) {
                    if (q.isNotEmpty()) q.append('\n')
                    q.append(QUOTE.find(lines[i])!!.groupValues[1])
                    i++
                }
                out.add(MdQuote(q.toString()))
                continue
            }
            '|' in line && i + 1 < lines.size && TABLE_SEP.matches(lines[i + 1]) -> {
                flush()
                val header = cells(line)
                val rows = mutableListOf<List<String>>()
                i += 2
                while (i < lines.size && '|' in lines[i] && lines[i].isNotBlank()) {
                    rows.add(cells(lines[i]))
                    i++
                }
                out.add(MdTable(header, rows))
                continue
            }
            ITEM.matches(line) -> {
                flush()
                val items = mutableListOf<MdItem>()
                while (i < lines.size) {
                    val l = lines[i]
                    val m = ITEM.find(l)
                    if (m != null) {
                        val indent = m.groupValues[1].replace("\t", "    ").length
                        items.add(MdItem(indent / 2, m.groupValues[2], m.groupValues[3]))
                    } else if (l.isNotBlank() && l.startsWith(" ") && items.isNotEmpty()) {
                        val last = items.removeAt(items.lastIndex)       // продолжение пункта
                        items.add(last.copy(text = last.text + "\n" + l.trim()))
                    } else {
                        break
                    }
                    i++
                }
                out.add(MdList(items))
                continue
            }
            else -> {
                if (para.isNotEmpty()) para.append('\n')
                para.append(line)
            }
        }
        i++
    }
    flush()
    return out
}

// ================================================================ инлайн

private fun isWordChar(c: Char) = c.isLetterOrDigit()

/** **жирный**, *курсив*, _курсив_, ~~зачёркнутый~~, `код`, [ссылка](url). */
fun inlineMarkdown(text: String, code: SpanStyle, link: SpanStyle): AnnotatedString =
    buildAnnotatedString { appendInline(this, text, code, link) }

private fun appendInline(b: AnnotatedString.Builder, s: String, code: SpanStyle, link: SpanStyle) {
    var i = 0
    val n = s.length
    while (i < n) {
        val c = s[i]
        // экранирование
        if (c == '\\' && i + 1 < n && s[i + 1] in "\\`*_~[]()#>|-") {
            b.append(s[i + 1]); i += 2; continue
        }
        if (c == '`') {
            val j = s.indexOf('`', i + 1)
            if (j > i) {
                b.withStyle(code) { append(s.substring(i + 1, j)) }
                i = j + 1; continue
            }
        }
        if ((s.startsWith("**", i) || s.startsWith("__", i)) && i + 2 < n && !s[i + 2].isWhitespace()) {
            val marker = s.substring(i, i + 2)
            val j = s.indexOf(marker, i + 2)
            if (j > i + 2) {
                b.withStyle(SpanStyle(fontWeight = FontWeight.Bold)) {
                    appendInline(this, s.substring(i + 2, j), code, link)
                }
                i = j + 2; continue
            }
        }
        if (s.startsWith("~~", i)) {
            val j = s.indexOf("~~", i + 2)
            if (j > i + 2) {
                b.withStyle(SpanStyle(textDecoration = TextDecoration.LineThrough)) {
                    appendInline(this, s.substring(i + 2, j), code, link)
                }
                i = j + 2; continue
            }
        }
        if ((c == '*' || c == '_') && i + 1 < n && !s[i + 1].isWhitespace() && s[i + 1] != c &&
            (c == '*' || i == 0 || !isWordChar(s[i - 1]))      // snake_case — не курсив
        ) {
            var j = i + 1
            var found = -1
            while (j < n) {
                j = s.indexOf(c, j)
                if (j < 0) break
                val okBefore = !s[j - 1].isWhitespace()
                val okAfter = c == '*' || j + 1 >= n || !isWordChar(s[j + 1])
                val notDouble = j + 1 >= n || s[j + 1] != c
                if (okBefore && okAfter && notDouble) { found = j; break }
                j++
            }
            if (found > i + 1) {
                b.withStyle(SpanStyle(fontStyle = FontStyle.Italic)) {
                    appendInline(this, s.substring(i + 1, found), code, link)
                }
                i = found + 1; continue
            }
        }
        if (c == '[') {
            val close = s.indexOf("](", i + 1)
            val end = if (close > 0) s.indexOf(')', close + 2) else -1
            if (close > i && end > close) {
                val url = s.substring(close + 2, end).trim()
                if (url.startsWith("http://") || url.startsWith("https://")) {
                    b.withLink(LinkAnnotation.Url(url, TextLinkStyles(link))) {
                        appendInline(this, s.substring(i + 1, close), code, link)
                    }
                    i = end + 1; continue
                }
            }
        }
        b.append(c)
        i++
    }
}

// ============================================================== отрисовка

@Composable
fun MarkdownText(
    text: String,
    modifier: Modifier = Modifier,
    style: TextStyle = MaterialTheme.typography.bodyLarge,
    color: Color = LocalContentColor.current,
) {
    val blocks = remember(text) { parseMarkdown(text) }
    val codeSpan = SpanStyle(
        fontFamily = FontFamily.Monospace,
        background = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.08f),
    )
    val linkSpan = SpanStyle(color = MaterialTheme.colorScheme.primary, textDecoration = TextDecoration.Underline)
    fun inl(s: String) = inlineMarkdown(s, codeSpan, linkSpan)

    Column(modifier, verticalArrangement = Arrangement.spacedBy(6.dp)) {
        for (block in blocks) {
            when (block) {
                is MdPara -> Text(inl(block.text), style = style, color = color)
                is MdHeading -> Text(
                    inl(block.text),
                    style = when (block.level) {
                        1 -> MaterialTheme.typography.titleLarge
                        2 -> MaterialTheme.typography.titleMedium
                        else -> MaterialTheme.typography.titleSmall
                    },
                    fontWeight = FontWeight.Bold,
                    color = color,
                )
                is MdCode -> CodeBlock(block)
                is MdQuote -> Row(Modifier.height(IntrinsicSize.Min)) {
                    Box(
                        Modifier
                            .width(3.dp)
                            .fillMaxHeight()
                            .background(MaterialTheme.colorScheme.outline, RoundedCornerShape(2.dp))
                    )
                    Spacer(Modifier.width(8.dp))
                    Text(inl(block.text), style = style, fontStyle = FontStyle.Italic,
                        color = color.copy(alpha = 0.85f))
                }
                is MdList -> Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    for (item in block.items) {
                        Row(Modifier.padding(start = (item.level * 14).dp)) {
                            val bullet = when {
                                item.text.startsWith("[ ] ") -> "☐"
                                item.text.startsWith("[x] ") || item.text.startsWith("[X] ") -> "☑"
                                item.marker.first().isDigit() -> item.marker
                                item.level == 0 -> "•"
                                else -> "◦"
                            }
                            val body = if (bullet == "☐" || bullet == "☑") item.text.drop(4) else item.text
                            Text(bullet, style = style, color = color, modifier = Modifier.widthIn(min = 18.dp))
                            Spacer(Modifier.width(4.dp))
                            Text(inl(body), style = style, color = color)
                        }
                    }
                }
                is MdTable -> TableBlock(block, style, color, ::inl)
                MdRule -> HorizontalDivider(Modifier.padding(vertical = 4.dp))
            }
        }
    }
}

@Composable
private fun CodeBlock(block: MdCode) {
    val clipboard = LocalClipboardManager.current
    Surface(
        shape = RoundedCornerShape(8.dp),
        color = MaterialTheme.colorScheme.surface,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column {
            Row(Modifier.fillMaxWidth().padding(start = 10.dp), verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                Text(block.lang.ifBlank { "код" }, style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.weight(1f))
                TextButton(onClick = { clipboard.setText(AnnotatedString(block.code)) }) {
                    Text("Копировать", style = MaterialTheme.typography.labelSmall)
                }
            }
            Text(
                block.code,
                style = MaterialTheme.typography.bodySmall.copy(fontFamily = FontFamily.Monospace),
                softWrap = false,
                modifier = Modifier
                    .horizontalScroll(rememberScrollState())
                    .padding(start = 10.dp, end = 10.dp, bottom = 10.dp),
            )
        }
    }
}

@Composable
private fun TableBlock(
    block: MdTable,
    style: TextStyle,
    color: Color,
    fmt: (String) -> AnnotatedString,
) {
    val cols = maxOf(block.header.size, block.rows.maxOfOrNull { it.size } ?: 0)
    val border = MaterialTheme.colorScheme.outlineVariant
    Column(Modifier.horizontalScroll(rememberScrollState())) {
        (listOf(block.header) + block.rows).forEachIndexed { r, row ->
            Row {
                for (c in 0 until cols) {
                    Text(
                        fmt(row.getOrElse(c) { "" }),
                        style = style.copy(fontWeight = if (r == 0) FontWeight.Bold else style.fontWeight),
                        color = color,
                        modifier = Modifier
                            .border(0.5.dp, border)
                            .widthIn(min = 64.dp, max = 220.dp)
                            .padding(horizontal = 6.dp, vertical = 4.dp),
                    )
                }
            }
        }
    }
}
