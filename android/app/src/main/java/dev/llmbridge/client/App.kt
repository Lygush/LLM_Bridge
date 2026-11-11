package dev.llmbridge.client

import android.app.Application
import android.content.Context

class App : Application() {
    lateinit var repo: BridgeRepository
        private set

    override fun onCreate() {
        super.onCreate()
        repo = BridgeRepository(this)
    }
}

val Context.repo: BridgeRepository
    get() = (applicationContext as App).repo
