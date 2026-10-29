import { useEffect, useState } from 'react'
import './App.css'


const CHUNK_SIZE = 5 * 1024 * 1024
const MAX_FILE_SIZE = 500 * 1024 * 1024
const ALLOWED_VIDEO_EXTENSIONS = new Set([".mp4", ".mov", ".webm", ".mkv"])

function sendChunk(sessionId, index, chunk, token, onProgress) {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest()
    request.open(
      "PUT",
      `/api/uploads/sessions/${sessionId}/chunks/${index}/`,
    )
    request.setRequestHeader("Authorization", `Token ${token}`)
    request.setRequestHeader("Content-Type", "application/octet-stream")

    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded)
    }

    request.onload = () => {
      if (request.status >= 200 && request.status < 300) {
        resolve()
      } else if (request.status === 401) {
        reject(new Error("Your session expired. Please sign in again."))
      } else {
        let detail = `Chunk upload failed (${request.status}).`
        try {
          detail = JSON.parse(request.responseText).detail || detail
        } catch {}
        const error = new Error(detail)
        error.status = request.status
        reject(error)
      }
    }

    request.onerror = () => reject(new Error("Network error while sending a chunk."))
    request.send(chunk)
  })
}

async function sendChunkWithRetry(sessionId, index, chunk, token, onProgress) {
  const maxAttempts = 3

  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    try {
      await sendChunk(sessionId, index, chunk, token, onProgress)
      return
    } catch (error) {
      const isClientError = error.status >= 400 && error.status < 500
      if (isClientError || attempt === maxAttempts - 1) throw error

      await new Promise((resolve) =>
        setTimeout(resolve, 500 * 2 ** attempt),
      )
    }
  }
}

function normalizeUploadPage(payload) {
  const results = Array.isArray(payload) ? payload : payload.results || []
  return {
    results,
    count: Array.isArray(payload) ? results.length : payload.count ?? results.length,
    next: Array.isArray(payload) ? null : payload.next,
    previous: Array.isArray(payload) ? null : payload.previous,
  }
}

function localApiPath(url) {
  if (!url) return null
  const parsed = new URL(url, window.location.origin)
  return `${parsed.pathname}${parsed.search}`
}

function App() {
  const [token, setToken] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [email, setEmail] = useState('')
  const [signupRole, setSignupRole] = useState('creator')
  const [authMode, setAuthMode] = useState('login')
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [youtubePrivacy, setYoutubePrivacy] = useState('private')
  const [file, setFile] = useState(null)
  const [uploads, setUploads] = useState([])
  const [uploadPage, setUploadPage] = useState({ count: 0, next: null, previous: null })
  const [uploadPageUrl, setUploadPageUrl] = useState('/api/uploads/')
  const [uploadSearch, setUploadSearch] = useState('')
  const [uploadStatusFilter, setUploadStatusFilter] = useState('')
  const [sessions, setSessions] = useState([])
  const [profile, setProfile] = useState(null)
  const [youtubeConnection, setYoutubeConnection] = useState(null)
  const [creators, setCreators] = useState([])
  const [creatorId, setCreatorId] = useState('')
  const [collaborations, setCollaborations] = useState([])
  const [invitations, setInvitations] = useState([])
  const [editorUsername, setEditorUsername] = useState('')
  const [progress, setProgress] = useState(0)
  const [message, setMessage] = useState('')
  const [uploading, setUploading] = useState(false)

  async function loadUploads(authToken, pageUrl = '/api/uploads/') {
    try {
      const headers = { Authorization: `Token ${authToken}` }
      const requestUrl = localApiPath(pageUrl) || '/api/uploads/'
      const uploadResponse = await fetch(requestUrl, { headers })
      if (!uploadResponse.ok) {
        throw new Error('Could not load videos')
      }

      // Show available videos even if loading resumable sessions or profile data fails.
      const page = normalizeUploadPage(await uploadResponse.json())
      setUploads(page.results)
      setUploadPage({
        count: page.count,
        next: localApiPath(page.next),
        previous: localApiPath(page.previous),
      })
      setUploadPageUrl(requestUrl)

      const [sessionResponse, profileResponse] = await Promise.all([
        fetch('/api/uploads/sessions/', { headers }),
        fetch('/api/me/', { headers }),
      ])
      if (!sessionResponse.ok || !profileResponse.ok) {
        throw new Error('Could not load account data')
      }

      const [sessionData, profileData] = await Promise.all([
        sessionResponse.json(),
        profileResponse.json(),
      ])
      setSessions(sessionData)
      setProfile(profileData)

      if (profileData.role === 'editor') {
        const [creatorResponse, invitationResponse] = await Promise.all([
          fetch('/api/editor-creators/', { headers }),
          fetch('/api/editor-invitations/', { headers }),
        ])
        if (!creatorResponse.ok || !invitationResponse.ok) {
          throw new Error('Could not load editor access')
        }
        const [creatorData, invitationData] = await Promise.all([
          creatorResponse.json(),
          invitationResponse.json(),
        ])
        setCreators(creatorData)
        setInvitations(invitationData)
        setCreatorId((current) => current || String(creatorData[0]?.id || ''))
        setCollaborations([])
      } else {
        const collaborationResponse = await fetch('/api/collaborations/', { headers })
        if (!collaborationResponse.ok) throw new Error('Could not load editor access')
        setCollaborations(await collaborationResponse.json())
        setCreators([])
        setInvitations([])
        setCreatorId('')
        const youtubeResponse = await fetch('/api/youtube/status/', { headers })
        if (youtubeResponse.ok) {
          setYoutubeConnection(await youtubeResponse.json())
        }
      }
    } catch {
      setMessage('Could not load all account data. Please refresh the page.')
    }
  }

  useEffect(() => {
    const savedToken = localStorage.getItem('authToken') || sessionStorage.getItem('authToken')
    if (savedToken) {
      localStorage.setItem('authToken', savedToken)
      sessionStorage.removeItem('authToken')
      setToken(savedToken)
      loadUploads(savedToken)
    }
  }, [])

  useEffect(() => {
    const hasActivePublish = uploads.some((upload) =>
      ["queued", "publishing"].includes(upload.youtube_status),
    )
    if (!token || !hasActivePublish) return undefined

    const refreshUploads = async () => {
      try {
        const response = await fetch(uploadPageUrl, {
          headers: { Authorization: `Token ${token}` },
        })
        if (response.ok) {
          const page = normalizeUploadPage(await response.json())
          setUploads(page.results)
          setUploadPage({
            count: page.count,
            next: localApiPath(page.next),
            previous: localApiPath(page.previous),
          })
        }
      } catch {
        // Keep the last known status if the API is temporarily unavailable.
      }
    }

    const timer = window.setInterval(refreshUploads, 3000)
    return () => window.clearInterval(timer)
  }, [token, uploads, uploadPageUrl])

  async function handleLogin(event) {
    event.preventDefault()
    setMessage('Signing in…')

    try {
      const response = await fetch('/api/token/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      })

      if (!response.ok) {
        setMessage('Sign in failed. Check your username and password.')
        return
      }

      const data = await response.json()
      localStorage.setItem('authToken', data.token)
      setToken(data.token)
      setPassword('')
      setMessage('')
      await loadUploads(data.token)
    } catch {
      setMessage('Could not connect to the API.')
    }
  }

  async function handleConnectYoutube() {
    try {
      const response = await fetch('/api/youtube/connect/', {
        method: 'POST',
        headers: { Authorization: `Token ${token}` },
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Could not start YouTube connection.')
      window.location.assign(data.authorization_url)
    } catch (error) {
      setMessage(error.message)
    }
  }

  async function handleDiscardFailedSession(session) {
    const confirmed = window.confirm(
      `Discard "${session.title}" and delete its saved chunks?`,
    )
    if (!confirmed) return

    try {
      const response = await fetch(`/api/uploads/sessions/${session.id}/`, {
        method: "DELETE",
        headers: { Authorization: `Token ${token}` },
      })
      const data = response.status === 204 ? {} : await response.json()
      if (!response.ok) throw new Error(data.detail || "Could not discard the session.")

      setMessage("Failed session and saved chunks discarded.")
      await loadUploads(token)
    } catch (error) {
      setMessage(error.message)
    }
  }

  async function handleUploadDecision(sessionId, decision) {
    try {
      const response = await fetch(
        `/api/uploads/sessions/${sessionId}/approval/`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Token ${token}`,
          },
          body: JSON.stringify({ decision }),
        },
      )
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Could not update upload.')

      setMessage(
        decision === 'approve'
          ? 'Upload approved. Video is processing.'
          : 'Upload rejected.',
      )
      await loadUploads(token)
    } catch (error) {
      setMessage(error.message)
    }
  }

  async function handleRevokeEditor(accessId) {
    try {
      const response = await fetch(`/api/collaborations/${accessId}/`, {
        method: 'DELETE',
        headers: { Authorization: `Token ${token}` },
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Could not revoke access.')

      setMessage(`Access for ${data.editor} was revoked.`)
      await loadUploads(token)
    } catch (error) {
      setMessage(error.message)
    }
  }

  async function handleInviteEditor(event) {
    event.preventDefault()
    try {
      const response = await fetch('/api/collaborations/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Token ${token}`,
        },
        body: JSON.stringify({ editor_username: editorUsername }),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Could not invite editor.')

      setEditorUsername('')
      setMessage(`Invitation status: ${data.status}`)
      await loadUploads(token)
    } catch (error) {
      setMessage(error.message)
    }
  }

  async function handleInvitationDecision(accessId, decision) {
    try {
      const response = await fetch(
        `/api/editor-invitations/${accessId}/decision/`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Token ${token}`,
          },
          body: JSON.stringify({ decision }),
        },
      )
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Could not update invitation.')

      setMessage(`Invitation ${data.status}.`)
      await loadUploads(token)
    } catch (error) {
      setMessage(error.message)
    }
  }

  async function handleSignup(event) {
    event.preventDefault()
    setMessage('Creating your account…')

    try {
      const response = await fetch('/api/register/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username,
          email,
          password,
          role: signupRole,
        }),
      })
      const data = await response.json()

      if (!response.ok) {
        throw new Error(Array.isArray(data.detail) ? data.detail.join(' ') : data.detail)
      }

      localStorage.setItem('authToken', data.token)
      setToken(data.token)
      setPassword('')
      setMessage('')
      await loadUploads(data.token)
    } catch (error) {
      setMessage(error.message || 'Could not create the account.')
    }
  }

  async function handlePublishUpload(upload) {
    try {
      const response = await fetch(`/api/uploads/${upload.id}/publish/`, {
        method: "POST",
        headers: { Authorization: `Token ${token}` },
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || "Could not queue YouTube publishing.")

      await loadUploads(token)
      setMessage("YouTube publishing queued.")
    } catch (error) {
      setMessage(error.message)
    }
  }

  async function downloadUpload(upload) {
    try {
      const response = await fetch(`/api/uploads/${upload.id}/download/`, {
        headers: { Authorization: `Token ${token}` },
      })
      if (!response.ok) throw new Error("Download failed.")

      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = url
      link.download = upload.file.split("/").pop().split("?")[0]
      document.body.appendChild(link)
      link.click()
      link.remove()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (error) {
      setMessage(error.message)
    }
  }

  function handleLogout() {
    localStorage.removeItem('authToken')
    sessionStorage.removeItem('authToken')
    setToken('')
    setUploads([])
    setSessions([])
    setProfile(null)
    setCreators([])
    setCreatorId('')
    setCollaborations([])
    setInvitations([])
    setMessage('You have signed out.')
  }

  async function handleUpload(event) {
    event.preventDefault()

    if (!file || !title.trim()) {
      setMessage("Enter a title and choose a video file.")
      return
    }
    if (profile?.role === "editor" && !creatorId) {
      setMessage("Choose a creator who has accepted your invitation.")
      return
    }

    setUploading(true)
    setProgress(0)
    setMessage("Preparing resumable upload…")

    try {
      const fingerprint = `${title.trim()}:${description.trim()}:${youtubePrivacy}:${file.name}:${file.size}:${file.lastModified}:${creatorId}`
      const digest = await crypto.subtle.digest(
        "SHA-256",
        new TextEncoder().encode(fingerprint),
      )
      const clientKey = Array.from(new Uint8Array(digest))
        .map((byte) => byte.toString(16).padStart(2, "0"))
        .join("")
      const totalChunks = Math.ceil(file.size / CHUNK_SIZE)

      const sessionResponse = await fetch("/api/uploads/sessions/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Token ${token}`,
        },
        body: JSON.stringify({
          client_key: clientKey,
          title: title.trim(),
          description: description.trim(),
          youtube_privacy: youtubePrivacy,
          file_name: file.name,
          file_size: file.size,
          total_chunks: totalChunks,
          creator_id: profile?.role === "editor" ? Number(creatorId) : undefined,
        }),
      })

      const session = await sessionResponse.json()
      if (!sessionResponse.ok) {
        throw new Error(session.detail || "Could not start the upload.")
      }

      if (session.status === "completed") {
        setMessage("This file was already uploaded.")
        await loadUploads(token)
        return
      }

      const received = new Set(session.received_chunks)
      const uploadedBytes = new Map()

      for (const index of received) {
        uploadedBytes.set(
          index,
          file.slice(
            index * CHUNK_SIZE,
            Math.min((index + 1) * CHUNK_SIZE, file.size),
          ).size,
        )
      }

      const updateProgress = () => {
        const completedBytes = Array.from(uploadedBytes.values())
          .reduce((total, size) => total + size, 0)
        setProgress(Math.floor((completedBytes / file.size) * 100))
      }

      updateProgress()
      const pendingIndices = Array.from(
        { length: totalChunks },
        (_, index) => index,
      ).filter((index) => !received.has(index))
      const concurrency = 3

      for (let start = 0; start < pendingIndices.length; start += concurrency) {
        const batch = pendingIndices.slice(start, start + concurrency)
        setMessage(
          `Uploading chunks ${start + 1}–${start + batch.length} of ${pendingIndices.length}…`,
        )

        const results = await Promise.allSettled(
          batch.map(async (index) => {
            const chunkStart = index * CHUNK_SIZE
            const chunk = file.slice(
              chunkStart,
              Math.min(chunkStart + CHUNK_SIZE, file.size),
            )

            await sendChunkWithRetry(
              session.id,
              index,
              chunk,
              token,
              (loaded) => {
                uploadedBytes.set(index, loaded)
                updateProgress()
              },
            )

            uploadedBytes.set(index, chunk.size)
            updateProgress()
          }),
        )

        const failed = results.find((result) => result.status === "rejected")
        if (failed) throw failed.reason
      }

      setMessage("All chunks received. Finalizing video…")
      const completeResponse = await fetch(
        `/api/uploads/sessions/${session.id}/complete/`,
        {
          method: "POST",
          headers: { Authorization: `Token ${token}` },
        },
      )
      let completion = await completeResponse.json()

      if (!completeResponse.ok) {
        throw new Error(completion.detail || "Could not queue video processing.")
      }

      let uploadStatus = completion.status

      if (uploadStatus === "awaiting_approval") {
        setMessage("Upload sent to the creator for approval.")
        setTitle("")
        setDescription("")
        setYoutubePrivacy("private")
        setFile(null)
        document.getElementById("upload-form").reset()
        await loadUploads(token)
        return
      }

      for (let attempt = 0; uploadStatus !== "completed" && attempt < 150; attempt += 1) {
        if (uploadStatus === "failed") {
          throw new Error("Video assembly failed. Reselect the same file and title to retry.")
        }

        setMessage("Video is processing in the background…")
        await new Promise((resolve) => setTimeout(resolve, 2000))

        const statusResponse = await fetch(
          `/api/uploads/sessions/${session.id}/`,
          { headers: { Authorization: `Token ${token}` } },
        )
        completion = await statusResponse.json()

        if (!statusResponse.ok) {
          throw new Error(completion.detail || "Could not check upload status.")
        }

        uploadStatus = completion.status
      }

      if (uploadStatus !== "completed") {
        throw new Error("Still processing. You can return later and reselect the same file and title.")
      }

      setProgress(100)
      setMessage("Upload complete.")
      setTitle("")
      setDescription("")
      setYoutubePrivacy("private")
      setFile(null)
      document.getElementById("upload-form").reset()
      await loadUploads(token)
    } catch (error) {
      if (error.message.includes("session expired")) {
        handleLogout()
        setMessage("Please sign in again, then reselect the same file and title to resume.")
      } else {
        setMessage(`${error.message} You can reselect the same file and title to resume.`)
      }
    } finally {
      setUploading(false)
    }
  }

  return (
    <main>
      <p className="eyebrow">CREATOR WORKSPACE</p>
      <h1>YouTube Mediator</h1>
      <p className="intro">Securely coordinate video uploads with your team.</p>

      {!token ? (
        <form onSubmit={authMode === "signup" ? handleSignup : handleLogin}>
          <h2>{authMode === "signup" ? "Create account" : "Sign in"}</h2>
          <label>
            Username
            <input
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoComplete="username"
              required
            />
          </label>

          {authMode === "signup" && (
            <>
              <label>
                Email
                <input
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  autoComplete="email"
                  required
                />
              </label>
              <label>
                I am a
                <select
                  value={signupRole}
                  onChange={(event) => setSignupRole(event.target.value)}
                >
                  <option value="creator">Creator</option>
                  <option value="editor">Editor</option>
                </select>
              </label>
            </>
          )}

          <label>
            Password
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete={authMode === "signup" ? "new-password" : "current-password"}
              required
            />
          </label>

          <button>{authMode === "signup" ? "Create account" : "Sign in"}</button>
          <button
            type="button"
            className="auth-switch"
            onClick={() => {
              setAuthMode(authMode === "signup" ? "login" : "signup")
              setMessage("")
            }}
          >
            {authMode === "signup"
              ? "Already registered? Sign in"
              : "New here? Create an account"}
          </button>
        </form>
      ) : (
        <>
          <button className="sign-out" onClick={handleLogout}>Sign out</button>
          {profile?.role === 'creator' && (
            <section className="collaboration-panel">
              <h2>YouTube channel</h2>
              <p>
                {youtubeConnection?.connected
                  ? `Connected to ${youtubeConnection.channel_title}`
                  : 'No YouTube channel connected yet.'}
              </p>
              <button type="button" onClick={handleConnectYoutube}>
                {youtubeConnection?.connected ? 'Reconnect YouTube' : 'Connect YouTube'}
              </button>
            </section>
          )}

          {profile?.role === "creator" && (
            <section className="collaboration-panel">
              <h2>Editors</h2>
              <form className="invite-form" onSubmit={handleInviteEditor}>
                <label>
                  Invite an editor by username
                  <input
                    value={editorUsername}
                    onChange={(event) => setEditorUsername(event.target.value)}
                    placeholder="Editor username"
                    required
                  />
                </label>
                <button>Send invitation</button>
              </form>
              {collaborations.length > 0 && (
                <ul>
                  {collaborations.map((access) => (
                    <li key={access.id} className="upload-row">
                      <span>
                        <strong>{access.editor}</strong>
                        <small className="session-status">{access.status}</small>
                      </span>
                      {access.status !== "revoked" && access.status !== "rejected" && (
                        <button
                          type="button"
                          className="secondary-button"
                          onClick={() => handleRevokeEditor(access.id)}
                        >
                          {access.status === "accepted" ? "Revoke access" : "Cancel invite"}
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}

          {profile?.role === "editor" && invitations.length > 0 && (
            <section className="collaboration-panel">
              <h2>Editor invitations</h2>
              <ul>
                {invitations.map((invitation) => (
                  <li key={invitation.id} className="invitation-row">
                    <strong>{invitation.creator} invited you</strong>
                    <div>
                      <button
                        type="button"
                        onClick={() => handleInvitationDecision(invitation.id, "accept")}
                      >
                        Accept
                      </button>
                      <button
                        type="button"
                        className="secondary-button"
                        onClick={() => handleInvitationDecision(invitation.id, "reject")}
                      >
                        Decline
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <form id="upload-form" onSubmit={handleUpload}>
            {profile?.role === "editor" && (
              <label>
                Upload for creator
                <select
                  value={creatorId}
                  onChange={(event) => setCreatorId(event.target.value)}
                  required
                >
                  <option value="">Choose a creator</option>
                  {creators.map((creator) => (
                    <option key={creator.id} value={creator.id}>
                      {creator.username}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label>
              Video title
              <input
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="Enter a title"
                maxLength={100}
                required
              />
            </label>
            <label>
              Video description
              <textarea
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                placeholder="Describe your video"
                maxLength={5000}
                rows={4}
                required
              />
            </label>
            <label>
              YouTube privacy
              <select
                value={youtubePrivacy}
                onChange={(event) => setYoutubePrivacy(event.target.value)}
                required
              >
                <option value="private">Private</option>
                <option value="unlisted">Unlisted</option>
                <option value="public">Public</option>
              </select>
            </label>
            <label>
              Choose a video
              <input
                type="file"
                id="video-file"
                accept=".mp4,.mov,.webm,.mkv"
                onChange={(event) => {
                  const selectedFile = event.target.files[0] || null
                  if (!selectedFile) {
                    setFile(null)
                    return
                  }

                  const extension = selectedFile.name
                    .slice(selectedFile.name.lastIndexOf("."))
                    .toLowerCase()

                  if (!ALLOWED_VIDEO_EXTENSIONS.has(extension)) {
                    setFile(null)
                    setMessage("Choose an MP4, MOV, WEBM, or MKV video.")
                    event.target.value = ""
                    return
                  }

                  if (selectedFile.size > MAX_FILE_SIZE) {
                    setFile(null)
                    setMessage("The maximum file size is 500 MB.")
                    event.target.value = ""
                    return
                  }

                  setFile(selectedFile)
                  setMessage("")
                }}
              />
            </label>
            <button disabled={uploading}>
              {uploading ? `Uploading ${progress}%` : 'Upload video'}
            </button>
          </form>

          {uploading && (
            <div className="upload-progress">
              <div className="progress-label">
                <span>Uploading video</span>
                <strong>{progress}%</strong>
              </div>
              <div
                className="progress-track"
                role="progressbar"
                aria-valuenow={progress}
                aria-valuemin="0"
                aria-valuemax="100"
              >
                <div className="progress-fill" style={{ width: `${progress}%` }} />
              </div>
            </div>
          )}

          {sessions.length > 0 && (
            <>
              <h2>Resumable uploads</h2>
              <p className="resume-hint">
                Resume restores the saved title, description, and privacy. Choose the same file to continue.
              </p>
              <ul>
                {sessions.map((session) => (
                  <li key={session.id} className="session-row">
                    <span>
                      <strong>{session.title}</strong>
                      <small>{session.file_name}</small>
                    </span>
                    <div className="session-actions">
                      <span className="session-status">
                        {session.status} · {session.received_chunks.length}/{session.total_chunks} chunks
                      </span>
                      {profile?.role === "creator" && session.status === "awaiting_approval" && (
                        <>
                          <button
                            type="button"
                            onClick={() => handleUploadDecision(session.id, "approve")}
                          >
                            Approve
                          </button>
                          <button
                            type="button"
                            className="secondary-button"
                            onClick={() => handleUploadDecision(session.id, "reject")}
                          >
                            Reject
                          </button>
                        </>
                      )}
                      {(session.status === "pending" || session.status === "failed") && (
                        <button
                          type="button"
                          className="resume-button"
                          onClick={() => {
                            setTitle(session.title)
                            setDescription(session.description || "")
                            setYoutubePrivacy(session.youtube_privacy || "private")
                            if (profile?.role === "editor") setCreatorId(String(session.creator_id))
                            setMessage("Saved title, description, and privacy restored. Choose the same file, then click Upload to resume.")
                            document.getElementById("video-file")?.click()
                          }}
                        >
                          Resume
                        </button>
                      )}
                      {session.status === "failed" && (
                        <button
                          type="button"
                          className="secondary-button"
                          onClick={() => handleDiscardFailedSession(session)}
                        >
                          Discard failed
                        </button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </>
          )}

          {profile?.role === "creator" && (
            <>
              <div className="uploads-heading">
                <h2>Your uploads</h2>
                <div className="upload-search">
                  <input
                    type="search"
                    value={uploadSearch}
                    onChange={(event) => setUploadSearch(event.target.value)}
                    placeholder="Search video titles"
                    aria-label="Search video titles"
                  />
                  <select
                    value={uploadStatusFilter}
                    onChange={(event) => setUploadStatusFilter(event.target.value)}
                    aria-label="Filter by YouTube status"
                  >
                    <option value="">All statuses</option>
                    <option value="not_started">Not started</option>
                    <option value="queued">Queued</option>
                    <option value="publishing">Publishing</option>
                    <option value="published">Published</option>
                    <option value="failed">Failed</option>
                  </select>
                  <button
                    type="button"
                    className="secondary-button"
                    onClick={() => {
                      const params = new URLSearchParams()
                      const query = uploadSearch.trim()
                      if (query) params.set("search", query)
                      if (uploadStatusFilter) params.set("youtube_status", uploadStatusFilter)
                      const suffix = params.toString()
                      loadUploads(token, suffix ? `/api/uploads/?${suffix}` : "/api/uploads/")
                    }}
                  >
                    Search
                  </button>
                </div>
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => loadUploads(token, uploadPageUrl)}
                >
                  Refresh status
                </button>
              </div>
              {uploads.length === 0 ? (
                <p>{uploadSearch.trim() || uploadStatusFilter ? 'No matching videos.' : 'No uploads yet.'}</p>
              ) : (
                <ul>
                  {uploads.map((upload) => (
                    <li key={upload.id} className="upload-row">
                      <span>
                        <strong>{upload.title}</strong>
                        <small>
                          Saved locally · YouTube: {upload.youtube_status.replaceAll("_", " ")}
                        </small>
                        {upload.youtube_status === "failed" && upload.youtube_error && (
                          <small className="upload-error">{upload.youtube_error}</small>
                        )}
                        {upload.youtube_video_id && (
                          <a
                            className="youtube-video-link"
                            href={`https://www.youtube.com/watch?v=${upload.youtube_video_id}`}
                            target="_blank"
                            rel="noreferrer"
                          >
                            View on YouTube
                          </a>
                        )}
                      </span>
                      <div className="upload-actions">
                        {profile?.role === "creator"
                          && ["not_started", "failed"].includes(upload.youtube_status) && (
                            <button
                              type="button"
                              className="secondary-button"
                              onClick={() => handlePublishUpload(upload)}
                            >
                              {upload.youtube_status === "failed" ? "Retry YouTube" : "Publish to YouTube"}
                            </button>
                          )}
                        <button
                          type="button"
                          className="download-button"
                          onClick={() => downloadUpload(upload)}
                        >
                          Download
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
              {uploadPage.count > 20 && (
                <div className="upload-pagination">
                  <button
                    type="button"
                    className="secondary-button"
                    disabled={!uploadPage.previous}
                    onClick={() => loadUploads(token, uploadPage.previous)}
                  >
                    Previous
                  </button>
                  <span>{uploadPage.count} total videos</span>
                  <button
                    type="button"
                    className="secondary-button"
                    disabled={!uploadPage.next}
                    onClick={() => loadUploads(token, uploadPage.next)}
                  >
                    Next
                  </button>
                </div>
              )}
            </>
          )}
        </>
      )}

      <p role="status">{message}</p>
    </main>
  )
}

export default App
