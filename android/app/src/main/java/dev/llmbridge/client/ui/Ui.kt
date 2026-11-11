package dev.llmbridge.client.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.Reply
import androidx.compose.material.icons.rounded.AccountTree
import androidx.compose.material.icons.rounded.AutoAwesome
import androidx.compose.material.icons.rounded.AutoFixHigh
import androidx.compose.material.icons.rounded.AutoStories
import androidx.compose.material.icons.rounded.Brush
import androidx.compose.material.icons.rounded.CardGiftcard
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.ChevronLeft
import androidx.compose.material.icons.rounded.ChevronRight
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.Collections
import androidx.compose.material.icons.rounded.Edit
import androidx.compose.material.icons.rounded.ExpandLess
import androidx.compose.material.icons.rounded.ExpandMore
import androidx.compose.material.icons.rounded.Favorite
import androidx.compose.material.icons.rounded.FavoriteBorder
import androidx.compose.material.icons.rounded.Flag
import androidx.compose.material.icons.rounded.Forum
import androidx.compose.material.icons.rounded.Groups
import androidx.compose.material.icons.rounded.History
import androidx.compose.material.icons.rounded.Image
import androidx.compose.material.icons.rounded.Inventory2
import androidx.compose.material.icons.rounded.Memory
import androidx.compose.material.icons.rounded.Movie
import androidx.compose.material.icons.rounded.Paid
import androidx.compose.material.icons.rounded.Palette
import androidx.compose.material.icons.rounded.Payments
import androidx.compose.material.icons.rounded.Place
import androidx.compose.material.icons.rounded.Psychology
import androidx.compose.material.icons.rounded.PushPin
import androidx.compose.material.icons.rounded.RadioButtonUnchecked
import androidx.compose.material.icons.rounded.Replay
import androidx.compose.material.icons.rounded.Savings
import androidx.compose.material.icons.rounded.Schedule
import androidx.compose.material.icons.rounded.SentimentDissatisfied
import androidx.compose.material.icons.rounded.SentimentNeutral
import androidx.compose.material.icons.rounded.SentimentSatisfied
import androidx.compose.material.icons.rounded.Settings
import androidx.compose.material.icons.rounded.StickyNote2
import androidx.compose.material.icons.rounded.TheaterComedy
import androidx.compose.material.icons.rounded.Tune
import androidx.compose.material.icons.rounded.ViewHeadline
import androidx.compose.material.icons.rounded.Wallpaper
import androidx.compose.material3.Icon
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * Все значки приложения в одном месте (Material Icons, скруглённый стиль).
 * Экраны обращаются к ним по смыслу — AppIcons.Gift, а не по имени картинки.
 */
object AppIcons {
    val Magic: ImageVector get() = Icons.Rounded.AutoAwesome          // «заполнить моделью»
    val Pin: ImageVector get() = Icons.Rounded.PushPin
    val Draw: ImageVector get() = Icons.Rounded.Palette
    val Brush: ImageVector get() = Icons.Rounded.Brush
    val Coins: ImageVector get() = Icons.Rounded.Paid
    val Messenger: ImageVector get() = Icons.Rounded.Forum
    val Roleplay: ImageVector get() = Icons.Rounded.TheaterComedy
    val Tune: ImageVector get() = Icons.Rounded.Tune
    val Settings: ImageVector get() = Icons.Rounded.Settings
    val Novel: ImageVector get() = Icons.Rounded.AutoStories
    val Frame: ImageVector get() = Icons.Rounded.Movie
    val Forks: ImageVector get() = Icons.Rounded.AccountTree
    val Finish: ImageVector get() = Icons.Rounded.Flag
    val Recap: ImageVector get() = Icons.Rounded.History
    val Gift: ImageVector get() = Icons.Rounded.CardGiftcard
    val Borrow: ImageVector get() = Icons.Rounded.Savings
    val Repay: ImageVector get() = Icons.Rounded.Payments
    val Date: ImageVector get() = Icons.Rounded.Favorite
    val Place: ImageVector get() = Icons.Rounded.Place
    val Time: ImageVector get() = Icons.Rounded.Schedule
    val Health: ImageVector get() = Icons.Rounded.FavoriteBorder
    val Inventory: ImageVector get() = Icons.Rounded.Inventory2
    val Goals: ImageVector get() = Icons.Rounded.Flag
    val People: ImageVector get() = Icons.Rounded.Groups
    val Notes: ImageVector get() = Icons.Rounded.StickyNote2
    val Edit: ImageVector get() = Icons.Rounded.Edit
    val Image: ImageVector get() = Icons.Rounded.Image
    val Background: ImageVector get() = Icons.Rounded.Wallpaper
    val Gallery: ImageVector get() = Icons.Rounded.Collections
    val TextView: ImageVector get() = Icons.Rounded.ViewHeadline
    val Thought: ImageVector get() = Icons.Rounded.Psychology
    val Assistant: ImageVector get() = Icons.Rounded.AutoFixHigh
    val Memory: ImageVector get() = Icons.Rounded.Memory
    val Close: ImageVector get() = Icons.Rounded.Close
    val Check: ImageVector get() = Icons.Rounded.Check
    val Retry: ImageVector get() = Icons.Rounded.Replay
    val Empty: ImageVector get() = Icons.Rounded.RadioButtonUnchecked
    val More: ImageVector get() = Icons.Rounded.ExpandMore
    val Less: ImageVector get() = Icons.Rounded.ExpandLess
    val Prev: ImageVector get() = Icons.Rounded.ChevronLeft
    val Next: ImageVector get() = Icons.Rounded.ChevronRight
    val Reply: ImageVector get() = Icons.AutoMirrored.Rounded.Reply
    val MoodGood: ImageVector get() = Icons.Rounded.SentimentSatisfied
    val MoodNeutral: ImageVector get() = Icons.Rounded.SentimentNeutral
    val MoodBad: ImageVector get() = Icons.Rounded.SentimentDissatisfied
    val Love: ImageVector get() = Icons.Rounded.Favorite
}

/** Значок и подпись в одну строку — вместо эмодзи в тексте. */
@Composable
fun IconLabel(
    icon: ImageVector,
    text: String,
    modifier: Modifier = Modifier,
    style: TextStyle = MaterialTheme.typography.labelMedium,
    color: Color = LocalContentColor.current,
    iconSize: Dp = 16.dp,
    maxLines: Int = 1,
    italic: Boolean = false,
) {
    Row(modifier, verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(5.dp)) {
        Icon(icon, contentDescription = null, tint = color, modifier = Modifier.size(iconSize))
        if (text.isNotEmpty()) {
            Text(text, style = style, color = color, maxLines = maxLines, overflow = TextOverflow.Ellipsis,
                fontStyle = if (italic) FontStyle.Italic else null)
        }
    }
}

// ---------------------------------------------------------------- ширина экрана

/** Ширина колонки с текстом: на планшете и в альбомной ориентации строки не растягиваются. */
val ReadableWidth: Dp = 760.dp

/** Экран широкий (планшет, телефон на боку, раскладной) — можно ставить панели рядом. */
@Composable
fun isWideScreen(): Boolean = LocalConfiguration.current.screenWidthDp >= 840

/** Низкий экран — телефон на боку: вертикали мало, блоки кладём в ряд. */
@Composable
fun isLandscapePhone(): Boolean = LocalConfiguration.current.let {
    it.screenWidthDp > it.screenHeightDp && it.screenHeightDp < 520
}

/** Ширина пузыря сообщения: доля экрана, но не шире удобной для чтения. */
@Composable
fun bubbleWidth(mine: Boolean): Dp {
    val w = minOf(LocalConfiguration.current.screenWidthDp, ReadableWidth.value.toInt())
    return (w * (if (mine) 0.80f else 0.88f)).dp
}

/** Боковые поля для экранов с формами: на широком экране колонка остаётся по центру. */
@Composable
fun sidePadding(min: Int = 16): Dp =
    ((LocalConfiguration.current.screenWidthDp - ReadableWidth.value.toInt()) / 2).coerceAtLeast(min).dp

/** Содержимое по центру и не шире удобной для чтения колонки. */
@Composable
fun Centered(modifier: Modifier = Modifier, maxWidth: Dp = ReadableWidth, content: @Composable () -> Unit) {
    Box(modifier.fillMaxWidth(), contentAlignment = Alignment.TopCenter) {
        Box(Modifier.widthIn(max = maxWidth).fillMaxWidth()) { content() }
    }
}

// ------------------------------------------------------------------------ тема

private val Violet = Color(0xFF7C6CF2)
private val VioletDeep = Color(0xFF5B4BD6)
private val Rose = Color(0xFFE87AA4)
private val Teal = Color(0xFF4FC3B0)

private val DarkColors = darkColorScheme(
    primary = Color(0xFFB7ADFF),
    onPrimary = Color(0xFF1F1763),
    primaryContainer = Color(0xFF3B328F),
    onPrimaryContainer = Color(0xFFE5E0FF),
    secondary = Color(0xFF9AD8CC),
    onSecondary = Color(0xFF05372F),
    secondaryContainer = Color(0xFF1E3F3A),
    onSecondaryContainer = Color(0xFFC6F0E7),
    tertiary = Color(0xFFF4A9C4),
    onTertiary = Color(0xFF4A1230),
    tertiaryContainer = Color(0xFF5A2A41),
    onTertiaryContainer = Color(0xFFFFD9E6),
    background = Color(0xFF111118),
    onBackground = Color(0xFFE7E5F0),
    surface = Color(0xFF111118),
    onSurface = Color(0xFFE7E5F0),
    surfaceVariant = Color(0xFF2A2A38),
    onSurfaceVariant = Color(0xFFB4B2C6),
    surfaceContainerLowest = Color(0xFF0C0C12),
    surfaceContainerLow = Color(0xFF16161F),
    surfaceContainer = Color(0xFF1A1A25),
    surfaceContainerHigh = Color(0xFF22222F),
    surfaceContainerHighest = Color(0xFF2B2B3A),
    outline = Color(0xFF6C6A80),
    outlineVariant = Color(0xFF34344A),
)

private val LightColors = lightColorScheme(
    primary = VioletDeep,
    onPrimary = Color.White,
    primaryContainer = Color(0xFFE5E0FF),
    onPrimaryContainer = Color(0xFF1B1259),
    secondary = Color(0xFF1F7A6C),
    onSecondary = Color.White,
    secondaryContainer = Color(0xFFD3F1EB),
    onSecondaryContainer = Color(0xFF07352E),
    tertiary = Color(0xFFB24A77),
    onTertiary = Color.White,
    tertiaryContainer = Color(0xFFFFDCE8),
    onTertiaryContainer = Color(0xFF3F0F27),
    background = Color(0xFFFAF9FF),
    onBackground = Color(0xFF1B1B24),
    surface = Color(0xFFFAF9FF),
    onSurface = Color(0xFF1B1B24),
    surfaceVariant = Color(0xFFE6E4F2),
    onSurfaceVariant = Color(0xFF4A4960),
    surfaceContainerLowest = Color.White,
    surfaceContainerLow = Color(0xFFF4F2FC),
    surfaceContainer = Color(0xFFEFEDF8),
    surfaceContainerHigh = Color(0xFFE9E7F4),
    surfaceContainerHighest = Color(0xFFE2E0EE),
    outline = Color(0xFF7B7990),
    outlineVariant = Color(0xFFCBC9DB),
)

private val AppShapes = Shapes(
    extraSmall = RoundedCornerShape(8.dp),
    small = RoundedCornerShape(12.dp),
    medium = RoundedCornerShape(16.dp),
    large = RoundedCornerShape(22.dp),
    extraLarge = RoundedCornerShape(28.dp),
)

/** Акцентные цвета вне схемы Material — для новеллы и значков отношений. */
object Accent {
    val violet = Violet
    val rose = Rose
    val teal = Teal
}

/** Тема приложения: свои спокойные цвета (тёмная и светлая — по системе), мягкие скругления. */
@Composable
fun BridgeTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = if (isSystemInDarkTheme()) DarkColors else LightColors,
        shapes = AppShapes,
        content = content,
    )
}
