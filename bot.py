import asyncio
import os
import random
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from gigachat import GigaChat
from telegram import Update
from telegram.constants import ChatAction
from telegram.error import NetworkError
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GIGACHAT_CREDENTIALS = os.getenv("GIGACHAT_CREDENTIALS")
TELEGRAM_PROXY_URL = os.getenv("TELEGRAM_PROXY_URL", "").strip()

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("В файле .env не найден TELEGRAM_BOT_TOKEN")

if not GIGACHAT_CREDENTIALS:
    raise RuntimeError("В файле .env не найден GIGACHAT_CREDENTIALS")


COMMENT_STYLES = [
    (
        "дружелюбный с лёгкой иронией",
        60,
        """
Пиши дружелюбно и живо, с лёгкой доброй иронией.
Ирония должна быть мягкой, без сарказма, насмешек и грубости.
""",
    ),
    (
        "нейтральный",
        10,
        """
Пиши спокойно, сдержанно и нейтрально.
Без шуток, иронии, чрезмерных эмоций и оценочных суждений.
""",
    ),
    (
        "дружелюбный",
        5,
        """
Пиши тепло, открыто и доброжелательно.
Без иронии и сарказма.
""",
    ),
    (
        "с лёгким юмором",
        15,
        """
Добавь лёгкую уместную шутку.
Юмор должен быть понятным, добрым и не затрагивать внешность,
здоровье, национальность, религию или личные качества людей.
""",
    ),
    (
        "дерзкий",
        5,
        """
Пиши уверенно, энергично и слегка дерзко.
Без оскорблений, грубости, токсичности, унижения и агрессии.
""",
    ),
    (
        "милый",
        5,
        """
Пиши тепло, мягко и немного мило.
Не используй слишком много уменьшительных слов и эмодзи.
""",
    ),
]


def choose_comment_style() -> tuple[str, str]:
    style = random.choices(
        COMMENT_STYLES,
        weights=[item[1] for item in COMMENT_STYLES],
        k=1,
    )[0]

    style_name = style[0]
    style_instruction = style[2]

    print(f"Выбран стиль: {style_name}")

    return style_name, style_instruction


def create_gigachat_client() -> GigaChat:
    return GigaChat(
        base_url="https://api.giga.chat/v1",
        credentials=GIGACHAT_CREDENTIALS,
        scope="GIGACHAT_API_PERS",
        model="GigaChat-3-Ultra",
        timeout=90,
        verify_ssl_certs=False,
    )


def is_timeout_error(error: Exception) -> bool:
    error_text = str(error).lower()

    return any(
        phrase in error_text
        for phrase in (
            "timeout",
            "timed out",
            "connecttimeout",
            "readtimeout",
        )
    )


def generate_text_comment(text: str) -> str:
    style_name, style_instruction = choose_comment_style()

    prompt = f"""
Напиши естественный комментарий к публикации или сообщению в Telegram.

Выбранный стиль:
{style_name}

Инструкция по стилю:
{style_instruction}

Общие требования:
- отвечай по-русски;
- пиши 1–3 предложения;
- не пересказывай исходный текст;
- добавь уместную мысль, реакцию или наблюдение;
- пиши естественно и без канцелярита;
- не используй хэштеги;
- не начинай со слов «Комментарий:» или «Ответ:»;
- не сообщай, что ты нейросеть;
- не придумывай факты, которых нет в исходном тексте;
- не используй оскорбления, грубость и токсичность;
- не пиши название выбранного стиля в ответе.

Исходный текст:
{text}
"""

    with create_gigachat_client() as client:
        response = client.chat(prompt)
        return response.choices[0].message.content.strip()


def generate_image_comment(
    image_path: Path,
    caption: str,
) -> str:
    uploaded_file_id = None
    style_name, style_instruction = choose_comment_style()

    with create_gigachat_client() as client:
        try:
            with image_path.open("rb") as image_file:
                uploaded_file = client.upload_file(
                    image_file,
                    purpose="general",
                )

            uploaded_file_id = uploaded_file.id_

            prompt = f"""
Проанализируй изображение и подпись, затем напиши естественный
комментарий к публикации в Telegram.

Выбранный стиль:
{style_name}

Инструкция по стилю:
{style_instruction}

Общие требования:
- отвечай по-русски;
- пиши 1–3 предложения;
- учитывай и изображение, и подпись;
- не описывай изображение буквально;
- не пересказывай подпись;
- добавь уместную мысль, реакцию или наблюдение;
- пиши естественно и без канцелярита;
- не используй хэштеги;
- не начинай со слов «Комментарий:» или «Ответ:»;
- не сообщай, что ты нейросеть;
- не придумывай факты, которых нельзя понять из изображения или подписи;
- не используй оскорбления, грубость и токсичность;
- не пиши название выбранного стиля в ответе.

Подпись к изображению:
{caption or "Подписи нет"}
"""

            response = client.chat(
                {
                    "model": "GigaChat-3-Ultra",
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt,
                            "attachments": [uploaded_file_id],
                        }
                    ],
                    "temperature": 0.7,
                }
            )

            return response.choices[0].message.content.strip()

        finally:
            if uploaded_file_id:
                try:
                    client.delete_file(uploaded_file_id)
                except Exception as error:
                    print(
                        "Не удалось удалить файл из GigaChat:",
                        error,
                    )


async def run_with_one_retry(function, *args):
    try:
        return await asyncio.to_thread(
            function,
            *args,
        )

    except Exception as first_error:
        if not is_timeout_error(first_error):
            raise

        print(
            "GigaChat не ответил вовремя. "
            "Повтор через 2 секунды."
        )

        await asyncio.sleep(2)

        return await asyncio.to_thread(
            function,
            *args,
        )


async def keep_typing(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_thread_id: int | None = None,
) -> None:
    try:
        while True:
            try:
                await context.bot.send_chat_action(
                    chat_id=chat_id,
                    action=ChatAction.TYPING,
                    message_thread_id=message_thread_id,
                )
            except NetworkError:
                pass

            await asyncio.sleep(4)

    except asyncio.CancelledError:
        pass


async def forget_media_group(
    application: Application,
    media_group_id: str,
) -> None:
    await asyncio.sleep(3600)

    processed_groups = application.bot_data.get(
        "processed_media_groups",
        set(),
    )

    processed_groups.discard(media_group_id)


def is_first_photo_in_album(
    message,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    media_group_id = message.media_group_id

    if not media_group_id:
        return True

    processed_groups = context.application.bot_data.setdefault(
        "processed_media_groups",
        set(),
    )

    if media_group_id in processed_groups:
        return False

    processed_groups.add(media_group_id)

    asyncio.create_task(
        forget_media_group(
            context.application,
            media_group_id,
        )
    )

    return True


def should_answer_in_group(
    message,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    is_channel_post = bool(
        message.is_automatic_forward
    )

    bot_username = (
        context.bot.username or ""
    ).lower()

    message_text = (
        message.text
        or message.caption
        or ""
    ).lower()

    is_mention = bool(
        bot_username
        and f"@{bot_username}" in message_text
    )

    replied_message = message.reply_to_message

    is_reply_to_bot = bool(
        replied_message
        and replied_message.from_user
        and replied_message.from_user.id
        == context.bot.id
    )

    return (
        is_channel_post
        or is_mention
        or is_reply_to_bot
    )


def should_process_message(
    message,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    if message.chat.type == "private":
        return True

    return should_answer_in_group(
        message,
        context,
    )


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    message = update.message

    if not message:
        return

    await message.reply_text(
        "Бот работает. Отправь текст или фотографию."
    )


async def handle_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    message = update.message

    if not message or not message.text:
        return

    if (
        message.from_user
        and message.from_user.is_bot
        and not message.is_automatic_forward
    ):
        return

    if not should_process_message(
        message,
        context,
    ):
        return

    typing_task = asyncio.create_task(
        keep_typing(
            context,
            message.chat_id,
            message.message_thread_id,
        )
    )

    try:
        comment = await run_with_one_retry(
            generate_text_comment,
            message.text,
        )

        await message.reply_text(comment)

    except Exception as error:
        print(
            f"Ошибка обработки текста: {error}"
        )

        await message.reply_text(
            "Не удалось подготовить комментарий."
        )

    finally:
        typing_task.cancel()
        await typing_task


async def handle_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    message = update.message

    if not message or not message.photo:
        return

    if (
        message.from_user
        and message.from_user.is_bot
        and not message.is_automatic_forward
    ):
        return

    if not should_process_message(
        message,
        context,
    ):
        return

    if not is_first_photo_in_album(
        message,
        context,
    ):
        print(
            f"Фото из альбома {message.media_group_id} пропущено"
        )
        return

    typing_task = asyncio.create_task(
        keep_typing(
            context,
            message.chat_id,
            message.message_thread_id,
        )
    )

    temp_path: Path | None = None

    try:
        largest_photo = message.photo[-1]
        telegram_file = await largest_photo.get_file()

        with tempfile.NamedTemporaryFile(
            suffix=".jpg",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)

        await telegram_file.download_to_drive(
            custom_path=temp_path,
        )

        caption = message.caption or ""

        comment = await run_with_one_retry(
            generate_image_comment,
            temp_path,
            caption,
        )

        await message.reply_text(comment)

    except Exception as error:
        print(
            f"Ошибка обработки фото: {error}"
        )

        await message.reply_text(
            "Не удалось проанализировать фотографию."
        )

    finally:
        typing_task.cancel()
        await typing_task

        if temp_path and temp_path.exists():
            temp_path.unlink()


def main() -> None:
    builder = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .get_updates_connect_timeout(30)
        .get_updates_read_timeout(30)
    )
    if TELEGRAM_PROXY_URL:
        builder = builder.proxy(TELEGRAM_PROXY_URL).get_updates_proxy(TELEGRAM_PROXY_URL)
    app = builder.build()

    app.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.PHOTO,
            handle_photo,
        )
    )

    print(
        "Бот со случайными стилями комментариев запущен"
    )

    app.run_polling()


if __name__ == "__main__":
    main()
