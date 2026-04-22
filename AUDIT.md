# Audit du code existant — Hex Bot

## Résumé

| Sévérité | Nombre |
|---|---|
| 🔴 Critique | 1 |
| 🟠 Important | 4 |
| 🟡 Mineur | 4 |
| ✅ Bien | 7 |

---

## 🔴 Critique

### 1. Slack va retenter l'envoi — doublons de tâches possibles

**Fichier :** `app.py:34-41`

```python
if event_type == "app_mention":
    try:
        dispatch_app_mention(event)      # ← appel synchrone, peut prendre 1-3s
    except Exception:
        log.exception(...)

# Always respond quickly to Slack    ← le commentaire est trompeur
return "", 200                         # ← le 200 est envoyé APRÈS le traitement
```

Slack attend un HTTP 200 dans les **3 secondes**. Si l'appel à l'API Google Tasks est lent,
le timeout est dépassé et Slack renvoie l'événement jusqu'à 3 fois.
Résultat : les tâches peuvent être créées en double ou en triple.

**Correction :** lancer `dispatch_app_mention` dans un thread et répondre 200 immédiatement.

```python
import threading

if event_type == "app_mention":
    threading.Thread(target=dispatch_app_mention, args=(event,), daemon=True).start()

return "", 200
```

---

## 🟠 Important

### 2. Pas de déduplication des événements Slack

**Fichier :** `app.py`

Slack garantit une livraison "at least once" : même sans timeout, un événement peut arriver
deux fois en cas de problème réseau de son côté.
Le payload contient un `event_id` unique (`payload["event_id"]`) qui permettrait de dédupliquer.

Aujourd'hui le bot n'en tient pas compte. Une fois la persistance SQLite en place (Phase 1),
on pourra stocker les `event_id` récents (TTL 10 min suffit) pour ignorer les doublons.

---

### 3. Thread-safety : caches globaux non partagés entre workers Gunicorn

**Fichiers :** `google_tasks.py:9`, `slack_client.py:16`

```python
# google_tasks.py
_tasklist_cache: Dict[str, str] = {}   # dict en mémoire, par process

# slack_client.py
_bot_user_id: Optional[str] = ...      # variable globale, par process
```

Avec Gunicorn en multi-workers (plusieurs process), ces caches sont indépendants.
Conséquence concrète : deux requêtes simultanées sur des workers différents peuvent créer
la même tasklist en double dans Google Tasks.
Ce n'est pas catastrophique (les tâches finiront dans l'une des deux listes),
mais c'est un comportement non déterministe. À corriger en stockant le cache en base (SQLite).

---

### 4. Token Google révoqué non géré

**Fichier :** `google_tasks.py:11-28`

```python
def _get_service():
    global _tasks_service
    if _tasks_service is None:
        ...
        _tasks_service = build(...)
    return _tasks_service        # ← jamais réinitialisé après ça
```

Si le refresh token est révoqué (ex : l'utilisateur révoque l'accès depuis son compte Google),
`_tasks_service` reste en cache. Toutes les requêtes suivantes échouent avec une 401
sans aucune récupération possible jusqu'au redémarrage du process.

Correction : intercepter les erreurs d'authentification et remettre `_tasks_service = None`
pour forcer la réinitialisation.

---

### 5. `requirements.txt` sans versions épinglées

**Fichier :** `requirements.txt`

```
google-auth               ← pas de version
google-auth-oauthlib      ← pas de version
google-api-python-client  ← pas de version
```

Le build n'est pas reproductible : une mise à jour breaking d'une de ces libs cassera
le bot en production sans prévenir. Épingler les versions avec `pip freeze > requirements.txt`
après validation.

---

## 🟡 Mineur

### 6. Cache des noms Slack inutile entre requêtes

**Fichier :** `commands/tasks.py:29`

```python
self._user_name_cache: Dict[str, str] = {}
```

Ce cache vit dans l'instance `TasksCommand`, qui est recréée à chaque événement.
Il ne sert que dans un seul message (si le même utilisateur est mentionné plusieurs fois
dans la même commande). Une fois la base SQLite là, ce cache devrait vivre en base.

---

### 7. `get_refresh_token.py` mélangé avec le code applicatif

Script utilitaire one-shot à déplacer dans `scripts/` pour ne pas le confondre
avec du code qui tourne en production.

---

### 8. Commentaires en français dans `google_tasks.py`

```python
# Cherche une liste existante avec ce titre
# Pas trouvée -> créer
```

Inconsistant avec le reste du code en anglais. À harmoniser.

---

### 9. Message de confirmation ambigu

**Fichier :** `commands/tasks.py:213`

```python
header = f"Created {created_count} Google Tasks in my list:"
```

"my list" laisse penser que c'est la liste du bot. Ce sera faux dès la Phase 2
où chaque utilisateur a sa propre liste. À reformuler : `"Created {created_count} task(s):"`.

---

## ✅ Ce qui est bien

1. **Vérification signature Slack correcte** (`slack_client.py:34-59`) :
   HMAC-SHA256, protection contre le replay (fenêtre 5 min),
   comparaison timing-safe avec `hmac.compare_digest`. Rien à redire.

2. **`.env` dans `.gitignore`** : les secrets ne risquent pas d'être commités.

3. **Configuration 100% depuis les variables d'environnement** (`config.py`) :
   propre, pas de secrets hardcodés dans le code.

4. **Error handling par tâche dans `TasksCommand`** (`tasks.py:208`) :
   une tâche qui échoue ne bloque pas les autres. Le bot rapporte combien
   ont réussi plutôt que de tout annuler.

5. **Pattern `@register_command`** (`commands/base.py`) :
   registre simple et extensible. Ajouter une nouvelle commande se fait
   en créant un fichier et en ajoutant un import dans `__init__.py`.

6. **Réponses éphémères pour les messages d'aide** (`dispatcher.py:86`) :
   `chat_postEphemeral` — seul l'utilisateur concerné voit le message,
   le channel n'est pas pollué.

7. **`get_bot_user_id()` avec auto-résolution** (`slack_client.py:18`) :
   `SLACK_BOT_USER_ID` est optionnel, le bot le résout lui-même via `auth.test`
   si non fourni.

---

## Priorités avant Phase 1

1. **Corriger le bug critique n°1** (thread + réponse 200 immédiate) — 10 lignes de code,
   risque de doublons en prod sinon.
2. **Épingler les versions** dans `requirements.txt` — 1 commande.
3. **Déplacer `get_refresh_token.py`** dans `scripts/` — cosmétique mais propre à faire maintenant.

Les points 2, 3, 4 (caches, token révoqué) seront naturellement résolus par la Phase 1 (SQLite)
et la Phase 2 (OAuth par utilisateur).
