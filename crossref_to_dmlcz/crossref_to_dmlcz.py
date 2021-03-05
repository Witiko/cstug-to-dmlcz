from typing import Iterable
from itertools import chain
from pathlib import Path

import click
from lxml import etree
from PyPDF2 import PdfFileReader, PdfFileWriter
import pycountry


NAMESPACES = {
    'crossref': 'http://www.crossref.org/schema/4.3.0',
}


class JournalIssue:
    def __init__(self, input_xml: Path, input_pdf: Path, page_offset: int, first_page_number: int):
        self.input_pdf = input_pdf
        self.page_offset = page_offset
        self.first_page_number = first_page_number

        input_xml = read_xml(input_xml)
        journal, = xpath(input_xml, 'crossref:body/crossref:journal')

        articles = xpath(journal, 'crossref:journal_article')
        articles = map(JournalArticle, articles)
        articles = list(articles)
        self.articles = articles

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
    def __init__(self, journal_article: etree._Element):
        language = journal_article.attrib['language']
        language = normalize_language(language)
        self.language = language
        self._load_titles(journal_article)
        self._load_authors(journal_article)
        self._load_pages(journal_article)
        self._load_doi(journal_article)
        self._load_category()
        self._load_references(journal_article)

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

        if self.doi is not None:
            doi = etree.SubElement(article, 'doi')
            doi.text = self.doi

        category = etree.SubElement(article, 'category')
        category.text = self.category

        range_pages = etree.SubElement(article, 'range_pages')
        range_pages.text = '{}-{}'.format(*self.pages)

        output_dir.mkdir(exist_ok=True)
        write_xml(output_dir / 'meta.xml', document)

    def __write_references_xml(self, output_dir: Path):
        references = etree.Element('references')
        document = etree.ElementTree(references)

        for refid, prefix, title, author, suffix in self.references:
            reference = etree.SubElement(references, 'reference', id=refid)
            etree.SubElement(reference, 'prefix').text = prefix
            etree.SubElement(reference, 'title').text = title
            authors = etree.SubElement(reference, 'authors')
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
        titles = xpath(journal_article, 'crossref:titles/crossref:title')
        titles = chain(titles, xpath(journal_article, 'crossref:titles/crossref:original_language_title'))
        for title in titles:
            if 'language' in title.attrib:
                title_language = normalize_language(title.attrib['language'])
            else:
                title_language = self.language
            title_text = get_text(title)
            self.titles.add((title_language, title_text))
        self.titles = sorted(self.titles)

    def _load_authors(self, journal_article: etree._Element):
        self.authors = list()
        authors = xpath(journal_article, 'crossref:contributors/crossref:person_name[@sequence = "first"]')
        authors = chain(authors, xpath(journal_article, 'crossref:contributors/crossref:person_name[@sequence = "additional"]'))
        for author_order, author in enumerate(authors):
            author_order += 1
            first_name, = xpath(author, 'crossref:given_name')
            first_name = get_text(first_name)
            last_name, = xpath(author, 'crossref:surname')
            last_name = get_text(last_name)
            name = (last_name, first_name)
            self.authors.append((author_order, *name))

    def _load_pages(self, journal_article: etree._Element):
        first_page, = xpath(journal_article, 'crossref:pages/crossref:first_page')
        first_page = int(get_text(first_page))
        last_page, = xpath(journal_article, 'crossref:pages/crossref:last_page')
        last_page = int(get_text(last_page))
        if first_page > last_page:
            raise ValueError('First page ({}) greater than last page ({})'.format(first_page, last_page))
        self.pages = (first_page, last_page)

    def _load_doi(self, journal_article: etree._Element):
        dois = xpath(journal_article, 'crossref:doi_data/crossref:doi')
        if dois:
            doi, = dois
            self.doi = get_text(doi)
        else:
            self.doi = None

    def _load_category(self):
        self.category = 'informatics'

    def _load_references(self, journal_article: etree._Element):
        self.references = list()
        references = xpath(journal_article, 'crossref:citation_list/crossref:citation')
        for refid, reference in enumerate(references):
            refid += 1
            prefix = '[{}]'.format(refid)
            dois = xpath(reference, 'crossref:doi')
            if dois:
                doi, = dois
                doi = get_text(doi)
                title = None
                author = None
                suffix = '. DOI: {}'.format(doi)
            else:
                title, = xpath(reference, 'crossref:article_title')
                title = get_text(title)
                author,  = xpath(reference, 'crossref:author')
                author = get_text(author)
                suffix = '. {}. {}'.format(author, title)
            reference = (refid, prefix, title, author, suffix)
            self.references.append(reference)

    def __repr__(self):
        (_, author, __), *other_authors = self.authors
        if other_authors:
            author = '{} et al.'.format(author)
        (_, title), *__ = self.titles
        return '{}. {}. {}-{}'.format(author, title, *self.pages)


def get_text(element: etree._Element) -> str:
    texts = xpath(element, './/text()')
    texts = map(str.strip, texts)
    texts = filter(lambda x: x, texts)
    texts = ' '.join(texts).split()
    return ' '.join(texts)


def normalize_language(language_code: str) -> str:
    language = pycountry.languages.get(alpha_2=language_code)
    try:
        return language.bibliographic
    except AttributeError:
        return language.alpha_3


def xpath(element: etree._Element, expression: str) -> Iterable[etree._Element]:
    return element.xpath(expression, namespaces=NAMESPACES)


def read_xml(filename: Path) -> etree._Element:
    tree = etree.parse(str(filename))
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
@click.option('--input-xml', help='The input CrossRef XML.', type=click.Path(exists=True))
@click.option('--input-pdf', help='The input PDF with an issue.', type=click.Path(exists=True))
@click.option('--page-offset', default=0, help='The offset between PDF\'s first physical and logical pages')
@click.option('--first-page-number', default=1, help='The page name of the PDF\'s first logical page')
@click.option('--output-dir', help='The output DML-CZ directory with an issue.', type=click.Path(dir_okay=True))
def main(input_xml: str, input_pdf: str, page_offset: int, first_page_number: int, output_dir: str):
    issue = JournalIssue(Path(input_xml), Path(input_pdf), page_offset, first_page_number)
    issue.write_xml(Path(output_dir))
    print(issue)


if __name__ == '__main__':
    main()
