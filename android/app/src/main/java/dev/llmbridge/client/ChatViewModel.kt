package dev.llmbridge.client

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.launch

/** Тонкая прослойка между экраном и BridgeRepository. */
class ChatViewModel(app: Application) : AndroidViewModel(app) {
    val repo: BridgeRepository = app.repo

    val pairing = repo.pairing
    val conn = repo.conn
    val status = repo.status
    val chats = repo.chats
    val currentChatId = repo.currentChatId
    val messages = repo.messages
    val defaultPrompt = repo.defaultPrompt
    val defaultSettings = repo.defaultSettings
    val recommended = repo.recommended
    val profiles = repo.profiles
    val memory = repo.memory
    val events = repo.events
    val cards = repo.cards
    val relations = repo.relations
    val vnBackgrounds = repo.vnBackgrounds
    val vnPending = repo.vnPending
    fun loadVn() = viewModelScope.launch { repo.loadVn() }
    fun drawSprites(cardId: Long) = viewModelScope.launch { repo.drawSprites(cardId) }
    val coins = repo.coins
    val showRelations = repo.showRelations
    fun setShowRelations(v: Boolean) = repo.setShowRelations(v)
    fun resetRelations() = viewModelScope.launch { repo.resetRelations() }
    fun nudge() = viewModelScope.launch { repo.nudge() }
    fun gift(text: String, to: Long?, onResult: (Boolean) -> Unit) {
        viewModelScope.launch { onResult(repo.gift(text, to)) }
    }
    fun money(action: String, amount: Int, to: Long?) = viewModelScope.launch { repo.money(action, amount, to) }
    fun startDate(setup: String, to: Long?) = viewModelScope.launch { repo.startDate(setup, to) }
    fun finishDate() = viewModelScope.launch { repo.finishDate() }
    fun recap(onResult: (String?) -> Unit) { viewModelScope.launch { onResult(repo.recap()) } }
    fun setChatOption(key: String, value: Any?) = viewModelScope.launch { repo.setChatOption(key, value) }
    val cardFields = repo.cardFields
    val cardStages = repo.cardStages

    fun pair(p: Pairing) = repo.pair(p)

    fun forget() {
        LinkService.stop(getApplication<Application>())
        repo.forget()
    }

    fun connect() = LinkService.start(getApplication<Application>())
    fun reconnect() = repo.reconnectNow()

    fun openChat(id: Long) = repo.openChat(id)
    fun newChat() = repo.newChat()

    /** Возвращает через onResult, ушло ли сообщение (чтобы не терять набранный текст). */
    fun send(text: String, images: List<ByteArray>, replyAs: Long? = null, directive: Boolean = false,
             choice: Boolean = false, onResult: (Boolean) -> Unit) {
        viewModelScope.launch { onResult(repo.send(text, images, replyAs, directive, choice)) }
    }
    val proposals = repo.proposals
    fun answerProposal(id: Long, accept: Boolean) = viewModelScope.launch { repo.answerProposal(id, accept) }
    fun gallery(onResult: (List<GalleryItem>) -> Unit) { viewModelScope.launch { onResult(repo.gallery()) } }
    fun forks(onResult: (List<Fork>) -> Unit) { viewModelScope.launch { onResult(repo.forks()) } }
    fun drawBackground(name: String) = viewModelScope.launch { repo.drawBackground(name) }

    suspend fun image(name: String) = repo.image(name)

    fun loadProfiles() = viewModelScope.launch { repo.loadProfiles() }
    val imageRoutes = repo.imageRoutes
    val imageQuality = repo.imageQuality
    fun setImageRoute(task: String, profile: String) = viewModelScope.launch { repo.setImageRoute(task, profile) }
    fun setImageQuality(q: String) = viewModelScope.launch { repo.setImageQuality(q) }
    fun draw(prompt: String, profile: String?, width: Int, height: Int, steps: Int?, seed: Long?,
             enhance: Boolean, likeness: Boolean, onResult: (Boolean) -> Unit) {
        viewModelScope.launch { onResult(repo.draw(prompt, profile, width, height, steps, seed, enhance, likeness)) }
    }
    fun enhancePrompt(text: String, onResult: (Pair<String, String>?) -> Unit) {
        viewModelScope.launch { onResult(repo.enhancePrompt(text)) }
    }
    fun loadCards() = viewModelScope.launch { repo.loadCards() }
    fun createCard(kind: String, text: String, onResult: (Card?) -> Unit) {
        viewModelScope.launch { onResult(repo.createCard(kind, text)) }
    }
    fun saveCard(id: Long, data: Map<String, String>, onResult: (Card?) -> Unit = {}) {
        viewModelScope.launch { onResult(repo.saveCard(id, data)) }
    }
    fun deleteCard(id: Long) = viewModelScope.launch { repo.deleteCard(id) }
    fun rewriteField(id: Long, field: String, wish: String, data: Map<String, String>, onResult: (String?) -> Unit) {
        viewModelScope.launch { onResult(repo.rewriteField(id, field, wish, data)) }
    }
    fun drawPortrait(id: Long) = viewModelScope.launch { repo.drawPortrait(id) }
    fun startCharacterChat(id: Long, personaId: Long?, onResult: (Boolean) -> Unit) {
        viewModelScope.launch { onResult(repo.startCharacterChat(id, personaId)) }
    }
    fun redraw(id: Long) = viewModelScope.launch { repo.redraw(id) }
    fun saveImage(name: String) = viewModelScope.launch { repo.saveImage(name) }

    fun stop() = viewModelScope.launch { repo.cancel() }
    fun regenerate(id: Long, wish: String = "") = viewModelScope.launch { repo.regenerate(id, wish) }
    val lore = repo.lore
    fun loadLore(worldId: Long) = viewModelScope.launch { repo.loadLore(worldId) }
    fun saveLore(worldId: Long, e: LoreEntry) = viewModelScope.launch { repo.saveLore(worldId, e) }
    fun deleteLore(worldId: Long, id: Long) = viewModelScope.launch { repo.deleteLore(worldId, id) }
    fun generateLore(worldId: Long, text: String, onResult: (Boolean) -> Unit) {
        viewModelScope.launch { onResult(repo.generateLore(worldId, text)) }
    }
    fun createScene(mode: String, characterIds: List<Long>, personaId: Long?, worldId: Long?, setup: String,
                    style: String, onResult: (Boolean) -> Unit) {
        viewModelScope.launch { onResult(repo.createScene(mode, characterIds, personaId, worldId, setup, style)) }
    }
    fun saveState(msgId: Long, state: QuestState) = viewModelScope.launch { repo.saveState(msgId, state) }
    fun selectVariant(id: Long) = viewModelScope.launch { repo.selectVariant(id) }
    fun edit(id: Long, text: String) = viewModelScope.launch { repo.editMessage(id, text) }
    fun resend(id: Long, text: String) = viewModelScope.launch { repo.resend(id, text) }
    fun deleteMessage(id: Long) = viewModelScope.launch { repo.deleteMessage(id) }
    fun renameChat(id: Long, title: String) = viewModelScope.launch { repo.renameChat(id, title) }
    fun deleteChat(id: Long) = viewModelScope.launch { repo.deleteChat(id) }
    fun setSystemPrompt(text: String, makeDefault: Boolean) =
        viewModelScope.launch { repo.setSystemPrompt(text, makeDefault) }
    fun setSettings(s: GenSettings, makeDefault: Boolean) =
        viewModelScope.launch { repo.setSettings(s, makeDefault) }
    fun continueMessage(id: Long) = viewModelScope.launch { repo.continueMessage(id) }
    fun setPinned(id: Long, pinned: Boolean) = viewModelScope.launch { repo.setPinned(id, pinned) }

    fun openMemory() = viewModelScope.launch { repo.loadMemory() }
    fun closeMemory() = repo.closeMemory()
    fun addFact(text: String) = viewModelScope.launch { repo.addFact(text) }
    fun editFact(id: Long, text: String) = viewModelScope.launch { repo.editFact(id, text) }
    fun pinFact(id: Long, pinned: Boolean) = viewModelScope.launch { repo.pinFact(id, pinned) }
    fun deleteFact(id: Long) = viewModelScope.launch { repo.deleteFact(id) }
    fun saveChronicle(text: String) = viewModelScope.launch { repo.saveChronicle(text) }
    fun refreshMemory() = viewModelScope.launch { repo.refreshMemory() }
}
