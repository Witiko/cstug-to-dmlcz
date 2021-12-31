from typing import Iterable
from itertools import chain, repeat
from pathlib import Path
import re

import click
from lxml import etree
from PyPDF2 import PdfFileReader, PdfFileWriter
import pycountry


NAMESPACES = dict()
ELEMENT_REPLACEMENTS = {
    'CSTUG': 'CSTUG',
    'CSplain': 'CSplain',
    'Xe': 'Xe',
    'La': 'La',
    'TeX': 'TeX',
    'LaTeX': 'LaTeX',
    'XeTeX': 'XeTeX',
    'XeLaTeX': 'XeLaTeX',
    'encTeX': 'encTeX',
    'pdfTeX': 'pdfTeX',
    'pdfLaTeX': 'pdfLaTeX',
    'LuaTeX': 'LuaTeX',
    'LuaLaTeX': 'LuaLaTeX',
    'ConTeXt': 'ConTeXt',
    'Han': 'Hàn',
    'The': 'Thế',
    'Thanh': 'Thành',
    'br': '\n',
}


class JournalIssue:
    def __init__(self, input_xml: Path, input_pdf: Path, page_offset: int, first_page_number: int):
        self.input_pdf = input_pdf
        self.page_offset = page_offset

        journal = read_xml(input_xml)

        doi_base = journal.attrib['doi-base']
        year = journal.attrib['year']
        issue = journal.attrib['issue']
        doi = '{}/{}-{}'.format(doi_base, year, issue)

        articles = xpath(journal, 'article')
        articles = map(JournalArticle, zip(articles, repeat(doi)))
        articles = list(articles)
        assert articles
        self.articles = articles

    @property
    def first_page_number(self):
        return self.articles[0].pages[0]

    def write_xml(self, output_dir: Path):
        output_dir.mkdir(exist_ok=True)

        input_pdf = read_pdf(self.input_pdf)

        for article_number, article in enumerate(self.articles):
            article_number += 1
            article_number = '#{}'.format(article_number)
            article_directory = output_dir / article_number
            article.write_xml(article_directory)
            article.write_pdf(article_directory, input_pdf, self.page_offset, self.first_page_number)

    def __repr__(self):
        return '\n'.join(
            '#{}/ {}'.format(article_number+1, repr(article))
            for article_number, article
            in enumerate(self.articles)
        )


class JournalArticle:
    def __init__(self, journal_article: etree._Element, doi_base: str):
        language = journal_article.attrib['language']
        self.language = normalize_language(language)
        self._load_titles(journal_article)
        self._load_authors(journal_article)
        self._load_pages(journal_article)
        self._load_doi(journal_article, doi_base)
        self._load_category()
        self._load_references(journal_article)
        self._load_summaries()
        self._load_keywords()

    def write_xml(self, output_dir: Path):
        self._write_meta_xml(output_dir)
        if self.references:
            self._write_references_xml(output_dir)

    def _write_meta_xml(self, output_dir: Path):
        article = etree.Element('article')
        document = etree.ElementTree(article)

        for title_language, title_text in self.titles:
            title = etree.SubElement(article, 'title', lang=title_language)
            title.text = title_text

        for author_order, last_name, first_name in self.authors:
            author_order = str(author_order)
            author = etree.SubElement(article, 'author', order=author_order)
            author.text = '{}, {}'.format(last_name, first_name)

        language = etree.SubElement(article, 'language')
        language.text = self.language

        for keyword_language, keyword_text in self.keywords:
            keyword = etree.SubElement(article, 'keyword', lang=keyword_language)
            keyword.text = keyword_text

        for summary_language, summary_text in self.summaries:
            summary = etree.SubElement(article, 'summary', lang=summary_language)
            summary.text = summary_text

        if self.main_summary_language is not None:
            etree.SubElement(article, 'lang_summary').text = self.main_summary_language

        if self.doi is not None:
            doi = etree.SubElement(article, 'doi')
            doi.text = self.doi

        category = etree.SubElement(article, 'category')
        category.text = self.category

        range_pages = etree.SubElement(article, 'range_pages')
        range_pages.text = '{}-{}'.format(*self.pages)

        output_dir.mkdir(exist_ok=True)
        write_xml(output_dir / 'meta.xml', document)

    def _write_references_xml(self, output_dir: Path):
        references = etree.Element('references')
        document = etree.ElementTree(references)

        for refid, prefix, title, author_names, suffix in self.references:
            reference = etree.SubElement(references, 'reference', id=refid)
            etree.SubElement(reference, 'prefix').text = prefix
            etree.SubElement(reference, 'title').text = title
            authors = etree.SubElement(reference, 'authors')
            for first_name, last_name in author_names:
                author = '{}, {}'.format(last_name, first_name) if first_name else last_name
                etree.SubElement(authors, 'author').text = author
            etree.SubElement(reference, 'suffix').text = suffix

        output_dir.mkdir(exist_ok=True)
        write_xml(output_dir / 'references.xml', document)

    def write_pdf(self, output_dir: Path, input_pdf: PdfFileReader, page_offset: int, first_page_number: int):
        output_pdf = PdfFileWriter()

        first_page, last_page = self.pages
        for page_number in range(first_page, last_page + 1):
            page_number += page_offset
            page_number -= first_page_number
            page = input_pdf.getPage(page_number)
            output_pdf.addPage(page)

        output_dir.mkdir(exist_ok=True)
        write_pdf(output_dir / 'source.pdf', output_pdf)

    def _load_titles(self, journal_article: etree._Element):
        self.titles = set()

        # Main title
        title, = xpath(journal_article, 'titles/title')
        title_text = get_text(title)
        title_language = self.language

        subtitles = xpath(journal_article, 'titles/subtitle')
        for subtitle in subtitles:
            if subtitle.getprevious().tag != 'title':
                continue
            subtitle_text = get_text(subtitle)
            title_text = '{}: {}'.format(title_text, subtitle_text)
            break

        self.titles.add((title_language, title_text))

        # Original language title
        original_titles = xpath(journal_article, 'titles/original_language_title')
        if original_titles:
            original_title, = original_titles
            original_title_text = get_text(original_title)
            original_title_language = normalize_language(original_title.attrib['language'])

            original_subtitles = xpath(journal_article, 'titles/subtitle')
            for original_subtitle in original_subtitles:
                if original_subtitle.getprevious().tag != 'original_language_title':
                    continue
                original_subtitle_text = get_text(original_subtitle)
                original_title_text = '{}: {}'.format(original_title_text, original_subtitle_text)
                break

            self.titles.add((original_title_language, original_title_text))

        # Additional content title
        additional_titles = xpath(journal_article, 'additional-content/title')
        if additional_titles:
            additional_title, = additional_titles
            additional_title_text = get_text(additional_title)
            additional_title_language = invert_language(title_language)
            self.titles.add((additional_title_language, additional_title_text))

        self.titles = sorted(self.titles)

    def _load_authors(self, journal_article: etree._Element):
        self.authors = list()
        authors = xpath(journal_article, 'contributors/person_name[@sequence = "first"]')
        authors = chain(authors, xpath(journal_article, 'contributors/person_name[@sequence = "additional"]'))
        authors = (author for author in authors if author.attrib['contributor_role'] == 'author')
        for author_order, author in enumerate(authors):
            author_order += 1
            first_name, = xpath(author, 'given_name')
            first_name = get_text(first_name)
            last_name, = xpath(author, 'surname')
            last_name = get_text(last_name)
            name = (last_name, first_name)
            self.authors.append((author_order, *name))

    def _load_pages(self, journal_article: etree._Element):
        first_page, = xpath(journal_article, 'pages/first_page')
        first_page = int(get_text(first_page))
        last_page, = xpath(journal_article, 'pages/last_page')
        last_page = int(get_text(last_page))
        if first_page > last_page:
            raise ValueError('First page ({}) greater than last page ({})'.format(first_page, last_page))
        self.pages = (first_page, last_page)

    def _load_doi(self, journal_article: etree._Element, doi_base: str):
        if 'doi' in journal_article.attrib:
            self.doi = '{}/{}'.format(doi_base, journal_article.attrib['doi'])
        else:
            self.doi = None

    def _load_category(self):
        self.category = 'informatics'

    def _load_references(self, journal_article: etree._Element):
        self.references = list()
        references = xpath(journal_article, 'citation_list/citation')
        for refid, reference in enumerate(references):
            refid += 1
            prefix = '[{}]'.format(refid)
            dois = xpath(reference, 'doi')
            article_titles = xpath(reference, 'article_title')
            author_names = []
            if dois:
                doi, = dois
                doi = get_text(doi)
                title = None
                suffix = '. DOI: {}'.format(doi)
            elif article_titles:
                title, = article_titles
                title = get_text(title)
                authors = xpath(reference, 'contributors/person_name[@sequence = "first"]')
                authors = chain(authors, xpath(reference, 'contributors/person_name[@sequence = "additional"]'))
                authors = (author for author in authors if author.attrib['contributor_role'] == 'author')
                for author in authors:
                    first_names = xpath(author, 'given_name')
                    if first_names:
                        first_name, = first_names
                        first_name = get_text(first_name)
                    else:
                        first_name = None
                    last_names = xpath(author, 'surname')
                    last_name, = last_names
                    last_name = get_text(last_name)
                    author_names.append((first_name, last_name))
                suffix = ''
            else:
                message = 'Reference {} contains neither DOI nor article title'
                raise ValueError(message.format(refid))
            reference = (refid, prefix, title, author_names, suffix)
            self.references.append(reference)

    def _load_keywords(self, journal_article: etree._Element):
        self.keywords = []

        abstracts = xpath(journal_article, 'additional-content/abstract')
        for abstract in abstracts:

            keywords = xpath(abstract, 'keywords')
            if not keywords:
                continue
            keywords, = keywords
            keywords = get_text(keywords)

            keyword_texts = re.split(', *', keywords)
            if not keyword_texts:
                continue

            if abstract.getprevious().tag is None:
                keywords_language = self.language
            else:
                keywords_language = invert_language(self.language)

            for keyword_text in keyword_texts:
                keyword = (keyword_language, keyword_text)
                self.keywords.append(keyword)

    def _load_summaries(self, journal_article: etree._Element):
        self.summaries = set()
        self.main_summary_language = None

        abstracts = xpath(journal_article, 'additional-content/abstract')
        for abstract in abstracts:

            paragraphs = xpath(abstract, 'para')
            if not paragraphs:
                continue

            if abstract.getprevious().tag is None:
                summary_language = self.language
                self.main_summary_language = summary_language
            else:
                summary_language = invert_language(self.language)

            summary_text = '\n\n'.join(map(get_text, paragraphs))
            summary = (summary_language, summary_text)
            self.summaries.add(summary)

        self.summaries = sorted(self.summaries)

    def __repr__(self):
        (_, author, __), *other_authors = self.authors
        if other_authors:
            author = '{} et al.'.format(author)
        (_, title), *__ = self.titles
        return '{}. {}. {}-{}'.format(author, title, *self.pages)


def normalize_language(language_code: str) -> str:
    language = pycountry.languages.get(alpha_2=language_code)
    try:
        normalized_language = language.bibliographic
    except AttributeError:
        normalized_language = language.alpha_3
    assert normalized_language in ('cze', 'slo', 'eng')
    return normalized_language


def invert_language(language_code: str) -> str:
    language_code = normalize_language(language_code)
    if language_code in ('cze', 'slo'):
        inverted_language = 'eng'
    else:
        inverted_language 'cze or slo, please choose the correct one'
    return inverted_language


def get_text(element: etree._Element) -> str:
    element = etree.fromstring(etree.tostring(element))
    for replacement_element_name, replacement_text in ELEMENT_REPLACEMENTS.items():
        for replacement_element in xpath(element, replacement_element_name):
            replacement_element.text = replacement_text
    texts = xpath(element, './/text()')
    texts = map(str.strip, texts)
    texts = filter(lambda x: x, texts)
    texts = ' '.join(texts).split()
    return ' '.join(texts)


def xpath(element: etree._Element, expression: str) -> Iterable[etree._Element]:
    return element.xpath(expression, namespaces=NAMESPACES)


def read_xml(filename: Path) -> etree._Element:
    tree = etree.parse(str(filename))
    tree.xinclude()
    root = tree.getroot()
    if root.tag != '{{{}}}doi_batch'.format(NAMESPACES['crossref']):
        raise ValueError('Unexpected root element {}'.format(root.tag))
    return root


def write_xml(filename: Path, tree: etree.ElementTree):
    with filename.open('wb') as f:
        tree.write(f, xml_declaration=True, encoding='utf-8', pretty_print=True)


def read_pdf(filename: Path) -> PdfFileReader:
    reader = PdfFileReader(str(filename), strict=False)
    return reader


def write_pdf(filename: Path, pdf: PdfFileWriter):
    with filename.open('wb') as f:
        pdf.write(f)


@click.command()
@click.option('--input-xml', help='The input CSTUG XML.', type=click.Path(exists=True))
@click.option('--input-pdf', help='The input PDF with an issue.', type=click.Path(exists=True))
@click.option('--page-offset', default=2, help='The offset between PDF\'s first physical and logical pages')
@click.option('--output-dir', help='The output DML-CZ directory with an issue.', type=click.Path(dir_okay=True))
def main(input_xml: str, input_pdf: str, page_offset: int, output_dir: str):
    issue = JournalIssue(Path(input_xml), Path(input_pdf), page_offset)
    issue.write_xml(Path(output_dir))


if __name__ == '__main__':
    main()
